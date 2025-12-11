from flask import Flask, render_template, request, redirect, session, jsonify
import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler
import re 

def contains_arabic(text):
    return bool(re.search(r'[\u0600-\u06FF]', text or ""))


app = Flask(__name__)
app.secret_key = "secret_key_for_session"

# ✅ الاتصال بقاعدة البيانات
conn = psycopg2.connect(
    host="localhost",
    database="aiops_tickets",
    user="postgres",
    password="postghaida"
)
cursor = conn.cursor()

# -----------------------------------
@app.route('/')
def home():
    return redirect('/login')

# -----------------------------------
# ✅ تسجيل الدخول
@app.route('/login', methods=['GET', 'POST'])
def login():
    error_msg = None          # لرسالة الخطأ العامة (اسم المستخدم/كلمة المرور)
    arabic_error = None       # لرسالة "غير مسموح باستخدام الحروف العربية"
    employee_value = ""       # عشان نرجّع رقم الموظف اللي كتبه

    if request.method == 'POST':
        employee_id = request.form['employee_id'].strip()
        password = request.form['password']
        employee_value = employee_id

        # ✅ أولاً: منع الحروف العربية في رقم الموظف/كلمة المرور
        if contains_arabic(employee_id) or contains_arabic(password):
            arabic_error = "غير مسموح باستخدام الحروف العربية"
            return render_template(
                'login.html',
                error_msg=error_msg,
                arabic_error=arabic_error,
                employee_value=employee_value
            )

        # ✅ ثانياً: رقم الموظف لازم يكون أرقام فقط (عشان ما يخرب استعلام الـ DB)
        if not employee_id.isdigit():
            error_msg = "عذراً! اسم المستخدم أو كلمة المرور غير صحيحة، فضلاً تأكد من صحة المعلومات المدخلة."
            return render_template(
                'login.html',
                error_msg=error_msg,
                arabic_error=None,
                employee_value=employee_value
            )

        # ✅ إذا عدّى الشيكات اللي فوق، نكمل مع قاعدة البيانات
        try:
            cursor.execute("""
                SELECT employee_id, name 
                FROM employees 
                WHERE employee_id=%s AND password=%s
            """, (employee_id, password))

            user = cursor.fetchone()

            if user:
                session['employee_id'] = user[0]
                session['employee_name'] = user[1]

                cursor.execute("SELECT 1 FROM it_team WHERE employee_id=%s", (employee_id,))
                is_it = cursor.fetchone()

                return redirect('/dashboard' if is_it else '/create_ticket')

            # لو ما فيه مستخدم → بيانات خطأ
            error_msg = "عذراً! اسم المستخدم أو كلمة المرور غير صحيحة، فضلاً تأكد من صحة المعلومات المدخلة."

        except Exception as e:
            # حل مشكلة InFailedSqlTransaction
            conn.rollback()
            error_msg = "حدث خطأ في الاتصال بقاعدة البيانات، الرجاء المحاولة مرة أخرى."

    return render_template(
        'login.html',
        error_msg=error_msg,
        arabic_error=arabic_error,
        employee_value=employee_value
    )


# -----------------------------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# -----------------------------------
# ✅ رفع بلاغ
@app.route('/create_ticket', methods=['GET', 'POST'])
def create_ticket():
    if 'employee_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        cursor.execute("""
            INSERT INTO tickets 
            (employee_id, title, description, category, priority, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'New', NOW())
            RETURNING ticket_id
        """, (
            session['employee_id'],
            request.form['title'],
            request.form['description'],
            request.form['category'],
            request.form['priority']
        ))

        ticket_id = cursor.fetchone()[0]
        conn.commit()

        # 🔥 توزيع تلقائي للتذكرة
        assign_ticket_auto(ticket_id, request.form['category'])

        return redirect('/my_tickets')

    return render_template('create_ticket.html', user_name=session['employee_name'])


# -----------------------------------
# ✅ بلاغاتي
@app.route('/my_tickets')
def my_tickets():
    if 'employee_id' not in session:
        return redirect('/login')

    cursor.execute("""
        SELECT 
            t.ticket_id,      -- 0
            t.title,          -- 1
            t.status,         -- 2
            t.created_at,     -- 3
            t.assigned_to,    -- 4
            e.name,           -- 5  اسم المسؤول
            t.description,    -- 6
            t.category,       -- 7
            t.priority        -- 8
        FROM tickets t
        LEFT JOIN employees e 
            ON t.assigned_to = e.employee_id
        WHERE t.employee_id = %s
        ORDER BY t.created_at DESC
    """, (session['employee_id'],))

    rows = cursor.fetchall()

    tickets = [{
        "ticket_id":       r[0],
        "title":           r[1],
        "status":          r[2],
        "created_at":      r[3],
        "assigned_to_name": r[5] if r[5] else "لم يتم استلامها",
        "description":     r[6],
        "category":        r[7],
        "priority":        r[8],
    } for r in rows]

    return render_template(
        'my_tickets.html',
        tickets=tickets,
        user_name=session['employee_name']
    )

# -----------------------------------
# ✅ الشات + التنبيهات
@app.route('/chat/<int:ticket_id>', methods=['GET', 'POST'])
def chat(ticket_id):
    if 'employee_id' not in session:
        return redirect('/login')

    employee_id = session['employee_id']
    employee_name = session['employee_name']

    cursor.execute("SELECT 1 FROM it_team WHERE employee_id=%s", (employee_id,))
    is_it = cursor.fetchone() is not None

    if request.method == 'POST':
        message_text = request.form['message_text']

        try:
            cursor.execute("""
                INSERT INTO messages (ticket_id, sender_id, message_text)
                VALUES (%s, %s, %s)
            """, (ticket_id, employee_id, message_text))

            cursor.execute("""
                SELECT employee_id, assigned_to
                FROM tickets 
                WHERE ticket_id = %s
            """, (ticket_id,))

            owner_id, assigned_to = cursor.fetchone()
            receiver_id = owner_id if assigned_to == employee_id else assigned_to

            if receiver_id:
                cursor.execute("""
                    INSERT INTO notifications 
                    (receiver_id, ticket_id, message, is_read, created_at)
                    VALUES (%s, %s, %s, FALSE, NOW())
                """, (
                    receiver_id,
                    ticket_id,
                    f"📩 رسالة جديدة من {employee_name}"
                ))

            conn.commit()

        except Exception as e:
            conn.rollback()
            print("CHAT ERROR:", e)

        return redirect(f'/chat/{ticket_id}')

    cursor.execute("""
        SELECT m.sender_id, e.name, m.message_text, m.sent_at
        FROM messages m
        LEFT JOIN employees e ON m.sender_id = e.employee_id
        WHERE m.ticket_id=%s
        ORDER BY m.sent_at ASC
    """, (ticket_id,))

    rows = cursor.fetchall()
    messages = [{
        "sender_name": r[1],
        "text": r[2],
        "time": r[3]
    } for r in rows]

    return render_template(
        'chat.html',
        ticket_id=ticket_id,
        messages=messages,
        user_name=employee_name,
        is_it=is_it
    )

# -----------------------------------
# ✅ لوحة تحكم IT ✅✅✅ (مصَحَّحة بالكامل)
# -----------------------------------
# ✅ لوحة تحكم IT (مع عرض التذاكر المحلولة للموظف)
@app.route('/dashboard')
def dashboard():
    if 'employee_id' not in session:
        return redirect('/login')

    employee_id = session['employee_id']

    # نتأكد إنه من فريق الـ IT
    cursor.execute("SELECT 1 FROM it_team WHERE employee_id=%s", (employee_id,))
    if not cursor.fetchone():
        return "لا تملك صلاحية الدخول"

    # ✅ الإحصائيات
    cursor.execute("""
        SELECT COUNT(*) 
        FROM tickets 
        WHERE status='In Progress' AND assigned_to=%s
    """, (employee_id,))
    active = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) 
        FROM tickets 
        WHERE status='New' AND assigned_to=%s
    """, (employee_id,))
    new = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) 
        FROM tickets 
        WHERE status='Resolved' AND assigned_to=%s
    """, (employee_id,))
    resolved = cursor.fetchone()[0]

    # ✅ آخر التذاكر (الجديدة + النشطة) مع كل التفاصيل
    cursor.execute("""
        SELECT 
            t.ticket_id,       -- 0
            t.title,           -- 1
            t.status,          -- 2
            owner.name,        -- 3  صاحب البلاغ
            t.assigned_to,     -- 4
            t.description,     -- 5
            t.category,        -- 6
            t.priority,        -- 7
            t.created_at       -- 8
        FROM tickets t
        LEFT JOIN employees owner 
            ON t.employee_id = owner.employee_id
        WHERE 
            (t.status='New' AND t.assigned_to=%s)
            OR
            (t.status='In Progress' AND t.assigned_to=%s)
        ORDER BY t.created_at DESC
    """, (employee_id, employee_id))

    rows = cursor.fetchall()

    tickets = []
    for r in rows:
        tickets.append({
            "ticket_id": r[0],
            "title": r[1],
            "status": r[2],
            "owner_name": r[3],
            "is_mine": (r[4] == employee_id),
            "description": r[5],
            "category": r[6],
            "priority": r[7],
            "created_at": r[8],
        })

    # ✅✅✅ التذاكر التي قام الموظف بحلّها (مع كل التفاصيل)
    cursor.execute("""
        SELECT 
            t.ticket_id,       -- 0
            t.title,           -- 1
            owner.name,        -- 2
            t.description,     -- 3
            t.category,        -- 4
            t.priority,        -- 5
            t.status,          -- 6
            t.created_at       -- 7
        FROM tickets t
        LEFT JOIN employees owner 
            ON t.employee_id = owner.employee_id
        WHERE t.status='Resolved' 
          AND t.assigned_to=%s
        ORDER BY t.created_at DESC
    """, (employee_id,))

    resolved_list = [{
        "ticket_id":   r[0],
        "title":       r[1],
        "owner_name":  r[2],
        "description": r[3],
        "category":    r[4],
        "priority":    r[5],
        "status":      r[6],
        "created_at":  r[7],
    } for r in cursor.fetchall()]

    print("RESOLVED LIST >>>", resolved_list)   


    return render_template(
        'dashboard.html',
        active=active,
        new=new,
        resolved=resolved,
        tickets=tickets,
        resolved_list=resolved_list,
        user_name=session['employee_name']
    )


# -----------------------------------
# ✅ قبول التذكرة
@app.route('/accept_ticket/<int:ticket_id>', methods=['POST'])
def accept_ticket(ticket_id):
    try:
        cursor.execute("""
            UPDATE tickets 
            SET assigned_to=%s, status='In Progress'
            WHERE ticket_id=%s
        """, (session['employee_id'], ticket_id))

        cursor.execute("SELECT employee_id FROM tickets WHERE ticket_id=%s", (ticket_id,))
        owner_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO notifications 
            (receiver_id, ticket_id, message, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (owner_id, ticket_id, "✅ تم استلام بلاغك"))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("ACCEPT ERROR:", e)

    return redirect('/dashboard')

# -----------------------------------

# ✅ إنهاء التذكرة
@app.route('/resolve_ticket/<int:ticket_id>', methods=['POST'])
def resolve_ticket(ticket_id):
    try:
        # نغيّر حالة التذكرة إلى Resolved
        cursor.execute("UPDATE tickets SET status='Resolved' WHERE ticket_id=%s", (ticket_id,))

        # نجيب صاحب البلاغ
        cursor.execute("SELECT employee_id FROM tickets WHERE ticket_id=%s", (ticket_id,))
        owner_id = cursor.fetchone()[0]

        # نرسل له تنبيه
        cursor.execute("""
            INSERT INTO notifications 
            (receiver_id, ticket_id, message, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (owner_id, ticket_id, "✅ تم إغلاق بلاغك بنجاح"))

        # 👈 هنا ننقص الـ workload من موظف الـ IT اللي حل التذكرة
        cursor.execute("""
            UPDATE it_team
            SET workload = GREATEST(workload - 1, 0)
            WHERE employee_id = %s
        """, (session['employee_id'],))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("RESOLVE ERROR:", e)

    return redirect('/dashboard')


# -----------------------------------

# ✅ رفض التذكرة مع حفظ السبب واسم الرافض
@app.route('/reject_ticket/<int:ticket_id>', methods=['POST'])
def reject_ticket(ticket_id):
    try:
        reason = request.form['reason']
        rejected_by = session['employee_id']   # موظف الـ IT اللي رفض البلاغ

        # تحديث حالة التذكرة إلى Rejected مع السبب واسم الرافض
        cursor.execute("""
            UPDATE tickets
            SET 
                status = 'Rejected',
                rejected_by = %s,
                rejected_reason = %s
            WHERE ticket_id = %s
        """, (rejected_by, reason, ticket_id))

        # جلب صاحب البلاغ لإرسال تنبيه له
        cursor.execute("SELECT employee_id FROM tickets WHERE ticket_id=%s", (ticket_id,))
        owner_id = cursor.fetchone()[0]

        cursor.execute("""
            INSERT INTO notifications 
            (receiver_id, ticket_id, message, is_read, created_at)
            VALUES (%s, %s, %s, FALSE, NOW())
        """, (
            owner_id,
            ticket_id,
            "❌ تم رفض بلاغك"
        ))

        # 👈 هنا ننقص الـ workload من موظف الـ IT الرافض
        cursor.execute("""
            UPDATE it_team
            SET workload = GREATEST(workload - 1, 0)
            WHERE employee_id = %s
        """, (rejected_by,))

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("REJECT ERROR:", e)

    return redirect('/dashboard')


# -----------------------------------
# ✅ جلب التنبيهات
@app.route('/get_notifications')
def get_notifications():
    cursor.execute("""
        SELECT id, ticket_id, message
        FROM notifications
        WHERE receiver_id=%s AND is_read=FALSE
        ORDER BY created_at DESC
    """, (session['employee_id'],))

    data = cursor.fetchall()

    return jsonify({
        "count": len(data),
        "notifications": data
    })

# -----------------------------------
@app.route('/mark_notification/<int:notif_id>')
def mark_notification(notif_id):
    cursor.execute("UPDATE notifications SET is_read=TRUE WHERE id=%s", (notif_id,))
    conn.commit()
    return "", 204

# -----------------------------------

# -----------------------------------
# ✅ توزيع التذكرة تلقائياً حسب التخصص وأقل Workload
def assign_ticket_auto(ticket_id, category):
    cursor.execute("""
        SELECT employee_id 
        FROM it_team
        WHERE specialization = %s
          AND availability_status = 'متاح'
          AND workload < max_load
        ORDER BY workload ASC
        LIMIT 1
    """, (category,))

    employee = cursor.fetchone()

    # لو ما فيه أحد بنفس التخصص → نختار Other
    if not employee:
        cursor.execute("""
            SELECT employee_id 
            FROM it_team
            WHERE specialization = 'Other'
              AND availability_status = 'متاح'
              AND workload < max_load
            ORDER BY workload ASC
            LIMIT 1
        """)
        employee = cursor.fetchone()

    if employee:
        employee_id = employee[0]

        # تحديث التذكرة ليتم إسنادها للموظف
        cursor.execute("""
            UPDATE tickets
            SET assigned_to = %s
            WHERE ticket_id = %s
        """, (employee_id, ticket_id))

        # زيادة الـ workload للموظف
        cursor.execute("""
            UPDATE it_team
            SET workload = workload + 1
            WHERE employee_id = %s
        """, (employee_id,))

        conn.commit()



# -----------------------------------
# ✅ إعادة توزيع التذكرة تلقائياً بعد 15 دقيقة لو ما تم قبولها
def reassign_expired_tickets():
    cursor.execute("""
        SELECT ticket_id, assigned_to, category
        FROM tickets
        WHERE status = 'New'
          AND created_at <= NOW() - INTERVAL '15 minutes'
    """)
    # لاحظي: شلنا AND assigned_to IS NOT NULL
    # عشان يشمل حتى التذاكر اللي ما انأسندت أبدًا أو اللي رجعنا فكّينا إسنادها

    tickets = cursor.fetchall()

    for ticket_id, old_employee, category in tickets:

        # لو التذكرة كانت منسندة لموظف → ننقص الـ workload منه
        if old_employee:
            cursor.execute("""
                UPDATE it_team
                SET workload = GREATEST(workload - 1, 0)
                WHERE employee_id = %s
            """, (old_employee,))

        # 🔁 نعيد منطق التوزيع من البداية
        assign_ticket_auto(ticket_id, category)

    # نسوي commit بعد ما نخلص من كل التذاكر
    conn.commit()


# -----------------------------------

# ✅ تشغيل جدولة إعادة التوزيع كل دقيقة
scheduler = BackgroundScheduler()
scheduler.add_job(reassign_expired_tickets, 'interval', minutes=1)
scheduler.start()


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)

