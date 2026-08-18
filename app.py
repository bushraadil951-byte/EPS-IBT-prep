from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json, os, csv, io, re, base64
from pypdf import PdfReader
from psycopg2cffi import compat
compat.register()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'eps-ibt-portal-secret-key')
app.jinja_env.filters['from_json'] = json.loads
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'sqlite:///database.db'
).replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}
db = SQLAlchemy(app)

SUBJECTS  = ['English', 'Mathematics', 'Science', 'Reasoning']
GRADES    = ['Grade 3', 'Grade 4', 'Grade 5']
SECTIONS_BY_SUBJECT = {
    'English':     ['Reading Comprehension', 'Grammar', 'Spelling', 'Vocabulary', 'Punctuation'],
    'Mathematics': ['Number Operations', 'Algebra', 'Geometry', 'Measurement', 'Data & Statistics'],
    'Science':     ['Life Science', 'Physical Science', 'Earth Science', 'Scientific Inquiry'],
    'Reasoning':   ['Verbal Reasoning', 'Non-Verbal Reasoning', 'Logical Thinking', 'Pattern Recognition'],
}

# ── MODELS ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role     = db.Column(db.String(20), nullable=False)
    grade    = db.Column(db.String(20), nullable=True)
    section  = db.Column(db.String(10), nullable=True)
    created  = db.Column(db.DateTime, default=datetime.utcnow)
    results  = db.relationship('TestResult', backref='student', lazy=True, cascade='all,delete-orphan')

class MockTest(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    subject    = db.Column(db.String(50), nullable=False)
    grade      = db.Column(db.String(20), nullable=False)
    difficulty = db.Column(db.String(20), default='Medium')
    duration   = db.Column(db.Integer, default=40)
    status     = db.Column(db.String(10), default='draft')
    questions  = db.Column(db.Text, default='[]')
    created    = db.Column(db.DateTime, default=datetime.utcnow)
    results    = db.relationship('TestResult', backref='test', lazy=True, cascade='all,delete-orphan')

class TestResult(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    student_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    test_id        = db.Column(db.Integer, db.ForeignKey('mock_test.id'), nullable=False)
    score          = db.Column(db.Integer, default=0)
    total          = db.Column(db.Integer, default=0)
    percent        = db.Column(db.Float, default=0.0)
    answers        = db.Column(db.Text, default='{}')
    section_scores = db.Column(db.Text, default='{}')
    time_taken     = db.Column(db.Integer, default=0)
    taken_at       = db.Column(db.DateTime, default=datetime.utcnow)

# ── HELPERS ──────────────────────────────────────────────────────────────────

def login_required(role=None):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('Access denied.', 'error')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def safe_avg(lst):
    lst = [x for x in lst if x is not None]
    return round(sum(lst)/len(lst), 1) if lst else 0

def generate_username(name, grade):
    first = re.sub(r'[^a-z0-9]', '', name.split()[0].lower())
    grade_num = re.sub(r'[^0-9]', '', grade)
    base = f"{first}_g{grade_num}"
    username = base
    counter = 1
    while User.query.filter_by(username=username).first():
        username = f"{base}{counter}"
        counter += 1
    return username

def generate_password(name, grade):
    first3 = name[:3].capitalize()
    grade_num = re.sub(r'[^0-9]', '', grade)
    return f"EPS@{first3}{grade_num}"

def parse_pdf_questions(file_stream):
    reader = PdfReader(file_stream)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    text = re.sub(r'  +', ' ', text)
    answers = {}
    ak_match = re.search(r'Answer\s+Key.*?(?=\Z)', text, re.DOTALL | re.IGNORECASE)
    if ak_match:
        ak_text = ak_match.group()
        pairs = re.findall(r'(\d+)\s+([A-D])', ak_text)
        for qnum, ans in pairs:
            answers[int(qnum)] = ans
        text = text[:ak_match.start()]
    question_blocks = re.split(r'\n(?=\d+\.\s)', text)
    questions = []
    for block in question_blocks:
        block = block.strip()
        num_match = re.match(r'^(\d+)\.\s+(.+)', block, re.DOTALL)
        if not num_match:
            continue
        qnum = int(num_match.group(1))
        rest = num_match.group(2).strip()
        option_pattern = r'([A-D])\)\s+(.+?)(?=\s+[A-D]\)\s+|\Z)'
        options_found = re.findall(option_pattern, rest, re.DOTALL)
        if not options_found:
            continue
        first_opt_pos = re.search(r'[A-D]\)', rest)
        q_text = rest[:first_opt_pos.start()].strip() if first_opt_pos else rest
        opts = {letter: val.strip() for letter, val in options_found}
        questions.append({
            'id': qnum,
            'section': 'General',
            'passage': None,
            'question': q_text,
            'options': [opts.get('A',''), opts.get('B',''), opts.get('C',''), opts.get('D','')],
            'answer': ['A','B','C','D'].index(answers.get(qnum,'A')) if answers.get(qnum,'A') in ['A','B','C','D'] else 0,
            'image': None,
        })
    return questions

def build_analytics():
    students    = User.query.filter_by(role='student').all()
    all_results = TestResult.query.all()
    overall_avg = safe_avg([r.percent for r in all_results])
    above80     = sum(1 for r in all_results if r.percent >= 80)
    below60     = sum(1 for r in all_results if r.percent < 60)
    grade_data = {}
    for g in GRADES:
        rs = [r for r in all_results if r.student.grade == g]
        grade_data[g] = {
            'avg': safe_avg([r.percent for r in rs]),
            'count': len(rs),
            'students': len([s for s in students if s.grade == g]),
        }
    subject_data = {}
    for sub in SUBJECTS:
        rs = [r for r in all_results if r.test.subject == sub]
        subject_data[sub] = {'avg': safe_avg([r.percent for r in rs]), 'count': len(rs)}
    grade_subject = {}
    for g in GRADES:
        grade_subject[g] = {}
        for sub in SUBJECTS:
            rs = [r for r in all_results if r.student.grade == g and r.test.subject == sub]
            grade_subject[g][sub] = safe_avg([r.percent for r in rs])
    section_data = {}
    for r in all_results:
        try:
            secs = json.loads(r.section_scores or '{}')
            for sec, v in secs.items():
                if v['total'] > 0:
                    pct = round(v['correct']/v['total']*100, 1)
                    section_data.setdefault(sec, []).append(pct)
        except Exception:
            pass
    section_avgs = {sec: safe_avg(vals) for sec, vals in section_data.items()}
    student_rows = []
    for s in students:
        rs = [r for r in all_results if r.student_id == s.id]
        sub_avgs = {sub: safe_avg([r.percent for r in rs if r.test.subject == sub]) for sub in SUBJECTS}
        student_rows.append({
            'id': s.id, 'name': s.name, 'grade': s.grade, 'section': s.section,
            'tests_taken': len(rs),
            'overall_avg': safe_avg([r.percent for r in rs]),
            'sub_avgs': sub_avgs,
        })
    student_rows.sort(key=lambda x: -x['overall_avg'])
    return dict(
        overall_avg=overall_avg, above80=above80, below60=below60,
        total_results=len(all_results), total_students=len(students),
        grade_data=grade_data, subject_data=subject_data,
        grade_subject=grade_subject, section_avgs=section_avgs,
        student_rows=student_rows, subjects=SUBJECTS, grades=GRADES,
    )

def seed_db():
    try:
        if User.query.first():
            return
    except Exception:
        return
    db.session.add(User(name='Bushra Khan', username='Organizer',
        password=generate_password_hash('bk*123', method='pbkdf2:sha256:10000'),
        role='Resource_Manager'))
    for name, uname in [('Mrs. Sharma','teacher1'),('Mr. Verma','teacher2')]:
        db.session.add(User(name=name, username=uname,
            password=generate_password_hash('teacher123', method='pbkdf2:sha256:10000'),
            role='teacher'))
    sample = [
        ('Aarav Sharma','aarav','Grade 3','A'),('Priya Mehta','priya','Grade 3','A'),
        ('Rohan Gupta','rohan','Grade 4','B'),('Sneha Patel','sneha','Grade 4','A'),
    ]
    for name, uname, grade, sec in sample:
        db.session.add(User(name=name, username=uname,
            password=generate_password_hash('student123', method='pbkdf2:sha256:10000'),
            role='student', grade=grade, section=sec))
    db.session.commit()
    print("✅ Database seeded — Organizer / bk*123")

# ── HEALTH CHECK ──────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    return 'OK', 200

# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role']    = user.role
            session['name']    = user.name
            role = user.role
            if role == 'Resource_Manager':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for(f"{role}_dashboard"))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── ADMIN ─────────────────────────────────────────────────────────────────────

@app.route('/admin')
@login_required('Resource_Manager')
def admin_dashboard():
    students  = User.query.filter_by(role='student').all()
    tests     = MockTest.query.all()
    results   = TestResult.query.all()
    avg_score = safe_avg([r.percent for r in results])
    recent    = sorted(results, key=lambda r: r.taken_at, reverse=True)[:8]
    return render_template('admin/dashboard.html',
        students=students, tests=tests, results=results,
        avg_score=avg_score, recent=recent, subjects=SUBJECTS, grades=GRADES)

@app.route('/admin/students', methods=['GET','POST'])
@login_required('Resource_Manager')
def admin_students():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            if User.query.filter_by(username=request.form['username']).first():
                flash('Username already exists.', 'error')
            else:
                db.session.add(User(
                    name=request.form['name'], username=request.form['username'],
                    password=generate_password_hash(request.form['password'], method='pbkdf2:sha256:10000'),
                    role='student', grade=request.form['grade'], section=request.form.get('section','A')))
                db.session.commit()
                flash(f"Student {request.form['name']} added successfully.", 'success')
        elif action == 'delete':
            user = db.session.get(User, int(request.form['user_id']))
            if user:
                db.session.delete(user); db.session.commit()
                flash('Student removed.', 'success')
        elif action == 'edit':
            user = db.session.get(User, int(request.form['user_id']))
            if user:
                user.name = request.form['name']
                user.grade = request.form['grade']
                user.section = request.form.get('section','A')
                if request.form.get('password'):
                    user.password = generate_password_hash(request.form['password'], method='pbkdf2:sha256:10000')
                db.session.commit()
                flash('Student updated.', 'success')
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    return render_template('admin/students.html', students=students, grades=GRADES)

@app.route('/admin/students/upload', methods=['GET','POST'])
@login_required('Resource_Manager')
def upload_students():
    preview = []
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'preview':
            file = request.files.get('csv_file')
            if not file or not file.filename.endswith('.csv'):
                flash('Please upload a valid .csv file.', 'error')
                return redirect(url_for('upload_students'))
            stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
            reader = csv.DictReader(stream)
            for row in reader:
                name    = row.get('name','').strip()
                grade   = row.get('grade','').strip()
                section = row.get('section','A').strip()
                if not name or not grade:
                    continue
                username = row.get('username','').strip() or generate_username(name, grade)
                password = row.get('password','').strip() or generate_password(name, grade)
                if grade.strip().isdigit():
                    grade = f"Grade {grade.strip()}"
                preview.append({'name': name, 'grade': grade, 'section': section,
                                'username': username, 'password': password})
            return render_template('admin/upload_students.html', preview=preview, grades=GRADES)
        elif action == 'confirm':
            names     = request.form.getlist('name')
            usernames = request.form.getlist('username')
            passwords = request.form.getlist('password')
            grades    = request.form.getlist('grade')
            sections  = request.form.getlist('section')
            added = 0; skipped = 0
            try:
                BATCH = 20
                for i in range(len(names)):
                    if not names[i] or not usernames[i] or not passwords[i]:
                        continue
                    if User.query.filter_by(username=usernames[i]).first():
                        skipped += 1; continue
                    hashed = generate_password_hash(passwords[i], method='pbkdf2:sha256:10000')
                    db.session.add(User(name=names[i], username=usernames[i], password=hashed,
                        role='student', grade=grades[i], section=sections[i]))
                    added += 1
                    if added % BATCH == 0:
                        db.session.commit()
                db.session.commit()
                msg = f'✅ {added} students added successfully!'
                if skipped:
                    msg += f' ({skipped} skipped — username already exists)'
                flash(msg, 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'❌ Error: {str(e)}', 'error')
            return redirect(url_for('admin_students'))
    return render_template('admin/upload_students.html', preview=preview, grades=GRADES)

@app.route('/admin/students/download-template')
@login_required('Resource_Manager')
def download_csv_template():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name','username','password','grade','section'])
    writer.writerow(['Ahmed Khan','ahmed_01','ahm@01','Grade 3','A'])
    writer.writerow(['Sara Ali','sara_02','sar@02','Grade 4','B'])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=students_template.csv'})

@app.route('/admin/students/download-credentials')
@login_required('Resource_Manager')
def download_credentials():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name','Grade','Section','Username'])
    for s in students:
        writer.writerow([s.name, s.grade, s.section, s.username])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=student_credentials.csv'})

@app.route('/admin/teachers', methods=['GET','POST'])
@login_required('Resource_Manager')
def admin_teachers():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            if User.query.filter_by(username=request.form['username']).first():
                flash('Username already exists.', 'error')
            else:
                db.session.add(User(name=request.form['name'], username=request.form['username'],
                    password=generate_password_hash(request.form['password'], method='pbkdf2:sha256:10000'),
                    role='teacher'))
                db.session.commit()
                flash('Teacher added.', 'success')
        elif action == 'delete':
            user = db.session.get(User, int(request.form['user_id']))
            if user: db.session.delete(user); db.session.commit()
            flash('Teacher removed.', 'success')
    teachers = User.query.filter_by(role='teacher').all()
    return render_template('admin/teachers.html', teachers=teachers)

@app.route('/admin/tests', methods=['GET','POST'])
@login_required('Resource_Manager')
def admin_tests():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            grade = request.form['grade']
            if grade == 'All Grades':
                for g in GRADES:
                    db.session.add(MockTest(
                        name=request.form['name'], subject=request.form['subject'],
                        grade=g, difficulty=request.form['difficulty'],
                        duration=int(request.form['duration']), status=request.form['status']))
                db.session.commit()
                flash('Test created for all grades.', 'success')
            else:
                db.session.add(MockTest(
                    name=request.form['name'], subject=request.form['subject'],
                    grade=grade, difficulty=request.form['difficulty'],
                    duration=int(request.form['duration']), status=request.form['status']))
                db.session.commit()
                flash('Test created.', 'success')
        elif action == 'edit':
            test_id = request.form.get('test_id')
            if test_id:
                t = db.session.get(MockTest, int(test_id))
                if t:
                    t.name       = request.form.get('name', t.name)
                    t.subject    = request.form.get('subject', t.subject)
                    t.grade      = request.form.get('grade', t.grade)
                    t.difficulty = request.form.get('difficulty', t.difficulty)
                    t.duration   = int(request.form.get('duration', t.duration))
                    t.status     = request.form.get('status', t.status)
                    db.session.commit()
                    flash('Test updated.', 'success')
        elif action == 'delete':
            test_id = request.form.get('test_id')
            if test_id:
                t = db.session.get(MockTest, int(test_id))
                if t:
                    db.session.delete(t); db.session.commit()
                    flash('Test deleted.', 'success')
        elif action == 'toggle':
            test_id = request.form.get('test_id')
            if test_id:
                t = db.session.get(MockTest, int(test_id))
                if t:
                    t.status = 'active' if t.status == 'draft' else 'draft'
                    db.session.commit()
    tests = MockTest.query.order_by(MockTest.created.desc()).all()
    all_grades = ['All Grades'] + GRADES
    return render_template('admin/tests.html', tests=tests, subjects=SUBJECTS, grades=GRADES, all_grades=all_grades)

@app.route('/admin/tests/<int:test_id>/questions', methods=['GET','POST'])
@login_required('Resource_Manager')
def admin_questions(test_id):
    test = db.session.get(MockTest, test_id)
    if not test: flash('Test not found.','error'); return redirect(url_for('admin_tests'))
    subject_sections = SECTIONS_BY_SUBJECT.get(test.subject, ['General'])
    if request.method == 'POST':
        qs = json.loads(test.questions or '[]')
        image_data = None
        img_file = request.files.get('question_image')
        if img_file and img_file.filename:
            ext = img_file.filename.rsplit('.', 1)[-1].lower()
            mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','gif':'image/gif','webp':'image/webp'}.get(ext,'image/png')
            raw = img_file.read()
            if len(raw) < 2 * 1024 * 1024:
                image_data = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
            else:
                flash('Image too large — max 2MB.', 'error')
        qs.append({
            'id': max((q['id'] for q in qs), default=0) + 1,
            'section': request.form['section'],
            'passage': request.form.get('passage') or None,
            'question': request.form['question'],
            'options': [request.form.get(f'opt{i}','') for i in range(4)],
            'answer': int(request.form['answer']),
            'image': image_data,
        })
        test.questions = json.dumps(qs)
        db.session.commit()
        flash('Question added.', 'success')
    questions = json.loads(test.questions or '[]')
    return render_template('admin/questions.html', test=test, questions=questions, subject_sections=subject_sections)

@app.route('/admin/tests/<int:test_id>/upload-pdf', methods=['POST'])
@login_required('Resource_Manager')
def upload_pdf_questions(test_id):
    test = db.session.get(MockTest, test_id)
    if not test:
        flash('Test not found.', 'error')
        return redirect(url_for('admin_tests'))
    file = request.files.get('pdf_file')
    if not file or not file.filename.endswith('.pdf'):
        flash('Please upload a valid PDF file.', 'error')
        return redirect(url_for('admin_questions', test_id=test_id))
    try:
        parsed = parse_pdf_questions(file.stream)
        if not parsed:
            flash('No questions found in PDF.', 'error')
            return redirect(url_for('admin_questions', test_id=test_id))
        existing = json.loads(test.questions or '[]')
        max_id = max((q['id'] for q in existing), default=0)
        for q in parsed:
            q['id'] = max_id + q['id']
            existing.append(q)
        test.questions = json.dumps(existing)
        db.session.commit()
        flash(f'✅ {len(parsed)} questions imported from PDF!', 'success')
    except Exception as e:
        flash(f'❌ Error reading PDF: {str(e)}', 'error')
    return redirect(url_for('admin_questions', test_id=test_id))

@app.route('/admin/questions/edit/<int:test_id>/<int:q_id>', methods=['POST'])
@login_required('Resource_Manager')
def edit_question(test_id, q_id):
    test = db.session.get(MockTest, test_id)
    if not test:
        flash('Test not found.', 'error')
        return redirect(url_for('admin_tests'))
    qs = json.loads(test.questions or '[]')
    for q in qs:
        if q['id'] == q_id:
            q['question'] = request.form.get('question', q['question'])
            q['section']  = request.form.get('section', q.get('section','General'))
            q['passage']  = request.form.get('passage') or None
            q['options']  = [request.form.get(f'opt{i}', q['options'][i] if i < len(q['options']) else '') for i in range(4)]
            q['answer']   = int(request.form.get('answer', q['answer']))
            img_file = request.files.get('question_image')
            if img_file and img_file.filename:
                ext = img_file.filename.rsplit('.', 1)[-1].lower()
                mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','gif':'image/gif','webp':'image/webp'}.get(ext,'image/png')
                raw = img_file.read()
                if len(raw) < 2 * 1024 * 1024:
                    q['image'] = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
                else:
                    flash('Image too large — max 2MB.', 'error')
            if request.form.get('remove_image'):
                q['image'] = None
            break
    test.questions = json.dumps(qs)
    db.session.commit()
    flash('Question updated.', 'success')
    return redirect(url_for('admin_questions', test_id=test_id))

@app.route('/admin/questions/delete/<int:test_id>/<int:q_id>', methods=['POST'])
@login_required('Resource_Manager')
def delete_question(test_id, q_id):
    test = db.session.get(MockTest, test_id)
    if test:
        qs = [q for q in json.loads(test.questions or '[]') if q['id'] != q_id]
        test.questions = json.dumps(qs)
        db.session.commit()
        flash('Question deleted.', 'success')
    return redirect(url_for('admin_questions', test_id=test_id))

@app.route('/admin/analytics')
@login_required('Resource_Manager')
def admin_analytics():
    data = build_analytics()
    return render_template('admin/analytics.html', **data)

@app.route('/admin/download/students')
@login_required('Resource_Manager')
def download_students_excel():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        flash('openpyxl not installed.', 'error')
        return redirect(url_for('admin_students'))
    students = User.query.filter_by(role='student').order_by(User.grade, User.section, User.name).all()
    wb = Workbook(); ws = wb.active; ws.title = "Students"
    headers = ["#","Name","Username","Grade","Section","Tests Taken","Average %","Joined"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1a3c6e")
        c.alignment = Alignment(horizontal="center")
    for idx, s in enumerate(students, 1):
        results = s.results
        avg = round(sum(r.percent for r in results)/len(results), 1) if results else 0
        row = [idx, s.name, s.username, s.grade, s.section or '-', len(results), avg, s.created.strftime('%d %b %Y')]
        for c, val in enumerate(row, 1):
            cell = ws.cell(row=idx+1, column=c, value=val)
            cell.alignment = Alignment(horizontal="center")
            if idx % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="EBF1F9")
    for col in ws.columns:
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(len(str(c.value or '')) for c in col)+4, 40)
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return Response(buf.read(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=EPS_Students.xlsx'})

@app.route('/admin/download/results')
@login_required('Resource_Manager')
def download_results_excel():
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        flash('openpyxl not installed.', 'error')
        return redirect(url_for('admin_analytics'))
    results = TestResult.query.order_by(TestResult.taken_at.desc()).all()
    wb = Workbook(); ws = wb.active; ws.title = "All Results"
    headers = ["#","Student Name","Username","Grade","Section","Test","Subject","Score","Total","%","Time","Date"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1a3c6e")
        c.alignment = Alignment(horizontal="center")
    for idx, r in enumerate(results, 1):
        mins = r.time_taken // 60; secs = r.time_taken % 60
        row = [idx, r.student.name, r.student.username, r.student.grade, r.student.section or '-',
               r.test.name, r.test.subject, r.score, r.total, r.percent,
               f"{mins}m {secs}s", r.taken_at.strftime('%d %b %Y')]
        for c, val in enumerate(row, 1):
            cell = ws.cell(row=idx+1, column=c, value=val)
            cell.alignment = Alignment(horizontal="center")
            if idx % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="EBF1F9")
    for col in ws.columns:
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(len(str(c.value or '')) for c in col)+4, 40)
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return Response(buf.read(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=EPS_Results.xlsx'})

# ── RESULTS TEMPLATE DOWNLOAD ────────────────────────────────────────────────

@app.route('/admin/download/results-template')
@login_required('Resource_Manager')
def download_results_template():
    tests = MockTest.query.all()
    # Get max questions across all tests
    max_q = max((len(json.loads(t.questions or '[]')) for t in tests), default=8)
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ['username'] + [f'q{i+1}' for i in range(max_q)]
    writer.writerow(headers)
    # Sample rows
    students = User.query.filter_by(role='student').limit(3).all()
    for s in students:
        writer.writerow([s.username] + ['' for _ in range(max_q)])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=results_template.csv'})


# ── IMPORT RESULTS FROM CSV ──────────────────────────────────────────────────

@app.route('/admin/import-results', methods=['GET','POST'])
@login_required('Resource_Manager')
def import_results():
    tests   = MockTest.query.all()
    preview = []
    errors  = []

    if request.method == 'POST':
        action  = request.form.get('action')
        test_id = int(request.form.get('test_id', 0))
        test    = db.session.get(MockTest, test_id)
        if not test:
            flash('Test not found.', 'error')
            return redirect(url_for('import_results'))

        questions  = json.loads(test.questions or '[]')
        total_q    = len(questions)
        opt_map    = {'A':0,'B':1,'C':2,'D':3,'a':0,'b':1,'c':2,'d':3}

        if action == 'preview':
            file = request.files.get('csv_file')
            if not file or not file.filename.endswith('.csv'):
                flash('Please upload a valid .csv file.', 'error')
                return redirect(url_for('import_results'))

            stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
            reader = csv.DictReader(stream)

            for row in reader:
                username = row.get('username','').strip()
                if not username:
                    continue
                user = User.query.filter_by(username=username).first()
                if not user:
                    errors.append(f"'{username}' not found — skipped")
                    continue
                existing = TestResult.query.filter_by(student_id=user.id, test_id=test_id).first()
                if existing:
                    errors.append(f"{username} already has a result — skipped")
                    continue

                answers = {}
                score   = 0
                section_scores = {}

                for i, q in enumerate(questions):
                    col          = f'q{i+1}'
                    given_letter = row.get(col,'').strip().upper()
                    given_idx    = opt_map.get(given_letter)
                    correct_idx  = q['answer']
                    sec          = q.get('section','General')
                    section_scores.setdefault(sec, {'correct':0,'total':0})
                    section_scores[sec]['total'] += 1
                    if given_idx is not None:
                        answers[str(q['id'])] = given_idx
                        if given_idx == correct_idx:
                            score += 1
                            section_scores[sec]['correct'] += 1

                percent = round(score/total_q*100, 1) if total_q else 0
                preview.append({
                    'username': username, 'name': user.name,
                    'user_id': user.id, 'score': score,
                    'total': total_q, 'percent': percent,
                    'answers': json.dumps(answers),
                    'section_scores': json.dumps(section_scores),
                })

            return render_template('admin/import_results.html',
                tests=tests, preview=preview, errors=errors,
                test_id=test_id, selected_test=test)

        elif action == 'confirm':
            userids   = request.form.getlist('user_id')
            scores    = request.form.getlist('score')
            totals    = request.form.getlist('total')
            percents  = request.form.getlist('percent')
            answers_l = request.form.getlist('answers')
            secs_l    = request.form.getlist('section_scores')
            added = 0
            for i in range(len(userids)):
                existing = TestResult.query.filter_by(student_id=int(userids[i]), test_id=test_id).first()
                if existing:
                    continue
                db.session.add(TestResult(
                    student_id=int(userids[i]), test_id=test_id,
                    score=int(scores[i]), total=int(totals[i]),
                    percent=float(percents[i]),
                    answers=answers_l[i], section_scores=secs_l[i],
                    time_taken=0,
                ))
                added += 1
            db.session.commit()
            flash(f'✅ {added} student results imported successfully!', 'success')
            return redirect(url_for('admin_analytics'))

    return render_template('admin/import_results.html',
        tests=tests, preview=[], errors=[],
        test_id=None, selected_test=None)


# ── TEACHER ───────────────────────────────────────────────────────────────────

@app.route('/teacher')
@login_required('teacher')
def teacher_dashboard():
    students  = User.query.filter_by(role='student').all()
    results   = TestResult.query.all()
    tests     = MockTest.query.filter_by(status='active').all()
    avg_score = safe_avg([r.percent for r in results])
    recent    = sorted(results, key=lambda r: r.taken_at, reverse=True)[:6]
    return render_template('teacher/dashboard.html',
        students=students, results=results, tests=tests, avg_score=avg_score, recent=recent)

@app.route('/teacher/students')
@login_required('teacher')
def teacher_students():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    student_data = []
    for s in students:
        rs = list(s.results)
        student_data.append({'student': s, 'tests_taken': len(rs), 'avg': safe_avg([r.percent for r in rs])})
    return render_template('teacher/students.html', student_data=student_data)

@app.route('/teacher/analytics')
@login_required('teacher')
def teacher_analytics():
    data = build_analytics()
    return render_template('teacher/analytics.html', **data)

# ── STUDENT ───────────────────────────────────────────────────────────────────

@app.route('/student')
@login_required('student')
def student_dashboard():
    student = db.session.get(User, session['user_id'])
    seen_tests = set()
    unique_results = []
    for r in sorted(student.results, key=lambda r: r.taken_at):
        if r.test_id not in seen_tests:
            seen_tests.add(r.test_id)
            unique_results.append(r)
    results = sorted(unique_results, key=lambda r: r.taken_at, reverse=True)
    tests   = MockTest.query.filter(
        MockTest.status=='active',
        db.or_(MockTest.grade==student.grade, MockTest.grade=='All Grades')
    ).all()
    completed_test_ids = [r.test_id for r in results]
    avg_sc = safe_avg([r.percent for r in results])
    return render_template('student/dashboard.html',
        student=student, results=results, tests=tests,
        completed_test_ids=completed_test_ids, avg_sc=avg_sc, subjects=SUBJECTS)

@app.route('/student/test/<int:test_id>')
@login_required('student')
def student_test(test_id):
    test = db.session.get(MockTest, test_id)
    if not test: return redirect(url_for('student_dashboard'))
    existing = TestResult.query.filter_by(student_id=session['user_id'], test_id=test_id).first()
    if existing:
        flash('You have already completed this test. Check your scores to review it.', 'error')
        return redirect(url_for('student_dashboard'))
    questions = json.loads(test.questions or '[]')
    return render_template('student/test.html', test=test, questions=questions)

@app.route('/student/submit/<int:test_id>', methods=['POST'])
@login_required('student')
def submit_test(test_id):
    test = db.session.get(MockTest, test_id)
    if not test: return jsonify({'error':'not found'}), 404
    existing = TestResult.query.filter_by(student_id=session['user_id'], test_id=test_id).first()
    if existing:
        return jsonify({'score': existing.score, 'total': existing.total,
                        'percent': existing.percent,
                        'section_scores': json.loads(existing.section_scores or '{}')})
    questions  = json.loads(test.questions or '[]')
    data       = request.get_json() or {}
    answers    = data.get('answers', {})
    time_taken = data.get('time_taken', 0)
    score = 0; section_scores = {}
    for q in questions:
        sec = q.get('section', 'General')
        section_scores.setdefault(sec, {'correct':0,'total':0})
        section_scores[sec]['total'] += 1
        if str(q['id']) in answers and answers[str(q['id'])] == q['answer']:
            score += 1; section_scores[sec]['correct'] += 1
    total   = len(questions)
    percent = round(score/total*100, 1) if total else 0
    db.session.add(TestResult(student_id=session['user_id'], test_id=test_id,
        score=score, total=total, percent=percent,
        answers=json.dumps(answers), section_scores=json.dumps(section_scores),
        time_taken=time_taken))
    db.session.commit()
    return jsonify({'score':score,'total':total,'percent':percent,'section_scores':section_scores})

@app.route('/student/scores')
@login_required('student')
def student_scores():
    student = db.session.get(User, session['user_id'])
    seen_tests = set()
    unique_results = []
    for r in sorted(student.results, key=lambda r: r.taken_at):
        if r.test_id not in seen_tests:
            seen_tests.add(r.test_id)
            unique_results.append(r)
    results = sorted(unique_results, key=lambda r: r.taken_at, reverse=True)
    return render_template('student/scores.html', student=student, results=results)

@app.route('/student/review/<int:result_id>')
@login_required('student')
def student_review(result_id):
    result = db.session.get(TestResult, result_id)
    if not result:
        flash('Result not found.', 'error')
        return redirect(url_for('student_scores'))
    student = db.session.get(User, session['user_id'])
    if result.student_id != student.id:
        flash('Access denied.', 'error')
        return redirect(url_for('student_scores'))
    test      = result.test
    questions = json.loads(test.questions or '[]')
    answers   = json.loads(result.answers or '{}')
    review = []
    for q in questions:
        qid       = str(q['id'])
        given_idx = answers.get(qid)
        correct   = q.get('answer', 0)
        if given_idx is None:
            status = 'unattempted'
        elif int(given_idx) == correct:
            status = 'correct'
        else:
            status = 'wrong'
        review.append({'question': q, 'given': int(given_idx) if given_idx is not None else None,
                       'correct': correct, 'status': status})
    return render_template('student/review.html',
        student=student, test=test, result=result, review=review)

# ── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/analytics')
@login_required('Resource_Manager')
def api_analytics():
    results  = TestResult.query.all()
    by_grade = {}
    for r in results:
        g = r.student.grade or 'Unknown'
        by_grade.setdefault(g, []).append(r.percent)
    return jsonify({g: round(sum(v)/len(v),1) for g,v in by_grade.items()})

# ── MAIN ──────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    seed_db()

if __name__ == '__main__':
    print("\n🎓 Eastern Public School — IBT Portal")
    print("   Admin: Organizer / bk*123\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
