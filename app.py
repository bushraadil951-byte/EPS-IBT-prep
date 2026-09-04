from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json
import os
import csv
import io
import re
import base64

from pypdf import PdfReader

from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors as rl_colors
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics import renderPDF

from psycopg2cffi import compat
compat.register()


# =============================================================================
# APP CONFIGURATION
# =============================================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    'SECRET_KEY',
    'eps-ibt-portal-secret-key'
)

app.jinja_env.filters['from_json'] = json.loads

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///database.db'
).replace('postgres://', 'postgresql://')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

db = SQLAlchemy(app)


# =============================================================================
# CONSTANTS
# =============================================================================

SUBJECTS = [
    'English',
    'Mathematics',
    'Science',
    'Reasoning'
]

# Subjects used for Diagnostic Tests
DT_SUBJECTS = [
    'English',
    'Hindi',
    'Maths',
    'Science',
    'Urdu',
    'ICT'
]

# Mock-test grades
GRADES = [
    'Grade 3',
    'Grade 4',
    'Grade 5'
]

# IMPORTANT:
# Diagnostic Tests are now available for Grades 1–5.
DT_GRADES = [
    'Grade 1',
    'Grade 2',
    'Grade 3',
    'Grade 4',
    'Grade 5'
]

DT_NUMBERS = [
    1, 2, 3, 4, 5, 6
]

DT_SECTIONS = [
    'A',
    'B',
    'C',
    'D'
]

ACADEMIC_YEAR = '2026-27'


SECTIONS_BY_SUBJECT = {
    'English': [
        'Reading Comprehension',
        'Grammar',
        'Spelling',
        'Vocabulary',
        'Punctuation'
    ],

    'Mathematics': [
        'Number Operations',
        'Algebra',
        'Geometry',
        'Measurement',
        'Data & Statistics'
    ],

    'Science': [
        'Life Science',
        'Physical Science',
        'Earth Science',
        'Scientific Inquiry'
    ],

    'Reasoning': [
        'Verbal Reasoning',
        'Non-Verbal Reasoning',
        'Logical Thinking',
        'Pattern Recognition'
    ],
}


TERMS = [
    'Term 1',
    'Term 2',
    'Term 3'
]


RATING_SCALE = {
    1: 'Beginning',
    2: 'Developing',
    3: 'Achieved',
    4: 'Exceeding'
}


RATING_COLORS = {
    1: '#ef4444',
    2: '#f59e0b',
    3: '#3b82f6',
    4: '#10b981'
}


# =============================================================================
# LEARNER PROFILE
# =============================================================================

LEARNER_PROFILE = [
    (
        'Inquirer',
        '\U0001F50D',
        'Nurtures curiosity and love of learning. Acquires skills to inquire and research independently.'
    ),

    (
        'Knowledgeable',
        '\U0001F4DA',
        'Explores concepts across disciplines. Engages with local and global issues.'
    ),

    (
        'Thinker',
        '\U0001F4A1',
        'Uses critical and creative thinking to tackle complex problems and make ethical decisions.'
    ),

    (
        'Communicator',
        '\U0001F5E3',
        'Expresses ideas confidently in multiple modes and collaborates effectively.'
    ),

    (
        'Principled',
        '\u2696',
        'Acts with integrity and honesty. Takes responsibility for actions and consequences.'
    ),

    (
        'Open-minded',
        '\U0001F30D',
        'Appreciates own and others cultures. Seeks and evaluates diverse perspectives.'
    ),

    (
        'Caring',
        '\u2764',
        'Shows empathy, compassion and respect. Makes a positive difference to others.'
    ),

    (
        'Risk-taker',
        '\U0001F680',
        'Approaches uncertainty with courage and creativity. Explores new ideas and strategies.'
    ),

    (
        'Balanced',
        '\u26A1',
        'Understands importance of intellectual, physical and emotional balance.'
    ),

    (
        'Reflective',
        '\U0001FA9E',
        'Thoughtfully considers learning and experiences to improve understanding and growth.'
    ),
]


# =============================================================================
# ATL SKILLS
# =============================================================================

ATL_SKILLS = {
    'Communication': {
        'Grade 3': [
            'Shares ideas clearly in class discussions',
            'Listens attentively when others speak',
            'Writes sentences with a clear beginning and end',
            'Reads aloud with expression and understanding'
        ],

        'Grade 4': [
            'Expresses ideas using appropriate vocabulary',
            'Asks clarifying questions during discussions',
            'Organises written work with introduction and conclusion',
            'Reads and summarises key information'
        ],

        'Grade 5': [
            'Communicates effectively for different audiences',
            'Evaluates and responds to others ideas respectfully',
            'Writes structured arguments with evidence',
            'Analyses texts and identifies authors purpose'
        ],
    },

    'Self-Management': {
        'Grade 3': [
            'Brings required materials to class',
            'Follows classroom routines independently',
            'Manages time during tasks with teacher support',
            'Stays on task with minimal reminders'
        ],

        'Grade 4': [
            'Organises work and materials independently',
            'Sets personal goals with teacher guidance',
            'Manages time effectively during class activities',
            'Reflects on learning with prompting'
        ],

        'Grade 5': [
            'Plans and organises multi-step tasks independently',
            'Sets and monitors personal learning goals',
            'Manages time across multiple responsibilities',
            'Reflects critically on own learning and progress'
        ],
    },

    'Research': {
        'Grade 3': [
            'Identifies information from given sources',
            'Distinguishes between fact and opinion with support',
            'Records information in own words',
            'Uses library and digital resources with guidance'
        ],

        'Grade 4': [
            'Selects relevant information from multiple sources',
            'Identifies reliable vs unreliable sources',
            'Organises research notes effectively',
            'Cites sources with teacher support'
        ],

        'Grade 5': [
            'Independently researches using varied sources',
            'Evaluates credibility and bias in sources',
            'Synthesises information to form conclusions',
            'Properly attributes sources and avoids plagiarism'
        ],
    },

    'Thinking': {
        'Grade 3': [
            'Makes connections between new and prior learning',
            'Identifies patterns and sequences',
            'Generates ideas during brainstorming',
            'Solves simple problems with support'
        ],

        'Grade 4': [
            'Asks why and what if questions',
            'Applies knowledge to new situations',
            'Identifies cause and effect relationships',
            'Evaluates solutions to problems'
        ],

        'Grade 5': [
            'Analyses information from multiple perspectives',
            'Creates original solutions to complex problems',
            'Transfers learning across subjects',
            'Justifies reasoning with evidence'
        ],
    },

    'Social': {
        'Grade 3': [
            'Takes turns and shares during group activities',
            'Shows kindness and respect to classmates',
            'Accepts different roles in group work',
            'Resolves conflicts with teacher support'
        ],

        'Grade 4': [
            'Contributes meaningfully to group discussions',
            'Encourages and supports peers',
            'Adapts role based on group needs',
            'Resolves minor conflicts independently'
        ],

        'Grade 5': [
            'Leads and participates effectively in groups',
            'Considers diverse perspectives in collaboration',
            'Negotiates and compromises to achieve goals',
            'Mediates conflicts constructively'
        ],
    },
}


ATL_DESCRIPTORS = {
    'Grade 3': {
        1: 'Beginning — Needs a lot of support to demonstrate this skill',
        2: 'Developing — Demonstrates this skill with some support',
        3: 'Achieved — Demonstrates this skill independently most of the time',
        4: 'Exceeding — Consistently demonstrates this skill and supports others',
    },

    'Grade 4': {
        1: 'Beginning — Rarely demonstrates this skill even with support',
        2: 'Developing — Demonstrates this skill with teacher guidance',
        3: 'Achieved — Independently demonstrates this skill consistently',
        4: 'Exceeding — Applies this skill in new contexts and models it for peers',
    },

    'Grade 5': {
        1: 'Beginning — Limited evidence of this skill',
        2: 'Developing — Growing evidence with scaffolding required',
        3: 'Achieved — Consistent and independent application of skill',
        4: 'Exceeding — Sophisticated application; leads and mentors others',
    },
}


# =============================================================================
# MODELS
# =============================================================================

class User(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    username = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(200),
        nullable=False
    )

    role = db.Column(
        db.String(20),
        nullable=False
    )

    grade = db.Column(
        db.String(20),
        nullable=True
    )

    section = db.Column(
        db.String(10),
        nullable=True
    )

    created = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    results = db.relationship(
        'TestResult',
        backref='student',
        lazy=True,
        cascade='all,delete-orphan'
    )


class MockTest(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    name = db.Column(
        db.String(200),
        nullable=False
    )

    subject = db.Column(
        db.String(50),
        nullable=False
    )

    grade = db.Column(
        db.String(20),
        nullable=False
    )

    difficulty = db.Column(
        db.String(20),
        default='Medium'
    )

    duration = db.Column(
        db.Integer,
        default=40
    )

    status = db.Column(
        db.String(10),
        default='draft'
    )

    questions = db.Column(
        db.Text,
        default='[]'
    )

    created = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    results = db.relationship(
        'TestResult',
        backref='test',
        lazy=True,
        cascade='all,delete-orphan'
    )


class TestResult(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    test_id = db.Column(
        db.Integer,
        db.ForeignKey('mock_test.id'),
        nullable=False
    )

    score = db.Column(
        db.Integer,
        default=0
    )

    total = db.Column(
        db.Integer,
        default=0
    )

    percent = db.Column(
        db.Float,
        default=0.0
    )

    answers = db.Column(
        db.Text,
        default='{}'
    )

    section_scores = db.Column(
        db.Text,
        default='{}'
    )

    time_taken = db.Column(
        db.Integer,
        default=0
    )

    taken_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


# =============================================================================
# IB MODELS
# =============================================================================

class ATLRating(db.Model):

    __tablename__ = 'atl_rating'

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    teacher_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=True
    )

    rater_type = db.Column(
        db.String(10),
        nullable=False,
        default='teacher'
    )

    term = db.Column(
        db.String(20),
        nullable=False
    )

    skill = db.Column(
        db.String(50),
        nullable=False
    )

    descriptor = db.Column(
        db.String(255),
        nullable=False
    )

    rating = db.Column(
        db.Integer,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    student = db.relationship(
        'User',
        foreign_keys=[student_id]
    )

    teacher = db.relationship(
        'User',
        foreign_keys=[teacher_id]
    )


class LearnerProfileRating(db.Model):

    __tablename__ = 'lp_rating'

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    teacher_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=True
    )

    rater_type = db.Column(
        db.String(10),
        nullable=False,
        default='teacher'
    )

    term = db.Column(
        db.String(20),
        nullable=False
    )

    attribute = db.Column(
        db.String(50),
        nullable=False
    )

    rating = db.Column(
        db.Integer,
        nullable=False
    )

    evidence = db.Column(
        db.Text,
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    student = db.relationship(
        'User',
        foreign_keys=[student_id]
    )

    teacher = db.relationship(
        'User',
        foreign_keys=[teacher_id]
    )


class StudentReflection(db.Model):

    __tablename__ = 'student_reflection'

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    term = db.Column(
        db.String(20),
        nullable=False
    )

    attribute = db.Column(
        db.String(50),
        nullable=False
    )

    reflection = db.Column(
        db.Text,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    student = db.relationship(
        'User',
        foreign_keys=[student_id]
    )


# =============================================================================
# DIAGNOSTIC TEST MODELS
# =============================================================================

class DiagnosticTest(db.Model):

    __tablename__ = 'diagnostic_test'

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    dt_number = db.Column(
        db.Integer,
        nullable=False
    )

    subject = db.Column(
        db.String(50),
        nullable=False
    )

    grade = db.Column(
        db.String(20),
        nullable=False
    )

    section = db.Column(
        db.String(10),
        nullable=True
    )

    max_marks = db.Column(
        db.Float,
        default=25
    )

    academic_year = db.Column(
        db.String(20),
        default=ACADEMIC_YEAR
    )

    test_date = db.Column(
        db.Date,
        nullable=True
    )

    created_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=True
    )

    created = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    marks = db.relationship(
        'DTMark',
        backref='dt',
        lazy=True,
        cascade='all,delete-orphan'
    )

    __table_args__ = (
        db.UniqueConstraint(
            'dt_number',
            'subject',
            'grade',
            'section',
            'academic_year',
            name='uq_dt_slot'
        ),
    )


class DTMark(db.Model):

    __tablename__ = 'dt_mark'

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    dt_id = db.Column(
        db.Integer,
        db.ForeignKey('diagnostic_test.id'),
        nullable=False
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=False
    )

    marks_obtained = db.Column(
        db.Float,
        nullable=False
    )

    remarks = db.Column(
        db.Text,
        nullable=True
    )

    entered_by = db.Column(
        db.Integer,
        db.ForeignKey('user.id'),
        nullable=True
    )

    entered_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    student = db.relationship(
        'User',
        foreign_keys=[student_id]
    )

    __table_args__ = (
        db.UniqueConstraint(
            'dt_id',
            'student_id',
            name='uq_dt_student'
        ),
    )


# =============================================================================
# AUTH HELPER
# =============================================================================

def login_required(role=None):

    from functools import wraps

    def decorator(f):

        @wraps(f)
        def decorated(*args, **kwargs):

            if 'user_id' not in session:
                return redirect(url_for('login'))

            if role:

                allowed_roles = (
                    role
                    if isinstance(role, (list, tuple))
                    else (role,)
                )

                if session.get('role') not in allowed_roles:

                    flash(
                        'Access denied.',
                        'error'
                    )

                    return redirect(
                        url_for('login')
                    )

            return f(*args, **kwargs)

        return decorated

    return decorator


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def safe_avg(lst):

    lst = [
        x for x in lst
        if x is not None
    ]

    return (
        round(
            sum(lst) / len(lst),
            1
        )
        if lst
        else 0
    )


def generate_username(name, grade):

    first = re.sub(
        r'[^a-z0-9]',
        '',
        name.split()[0].lower()
    )

    grade_num = re.sub(
        r'[^0-9]',
        '',
        grade
    )

    base = f"{first}_g{grade_num}"

    username = base
    counter = 1

    while User.query.filter_by(
        username=username
    ).first():

        username = f"{base}{counter}"

        counter += 1

    return username


def generate_password(name, grade):

    first3 = name[:3].capitalize()

    grade_num = re.sub(
        r'[^0-9]',
        '',
        grade
    )

    return f"EPS@{first3}{grade_num}"


# =============================================================================
# DT HELPERS
# =============================================================================

def dt_get_or_create(
    dt_number,
    subject,
    grade,
    section,
    academic_year=ACADEMIC_YEAR,
    max_marks=25,
    created_by=None
):

    dt = DiagnosticTest.query.filter_by(
        dt_number=dt_number,
        subject=subject,
        grade=grade,
        section=section,
        academic_year=academic_year
    ).first()

    if not dt:

        dt = DiagnosticTest(
            dt_number=dt_number,
            subject=subject,
            grade=grade,
            section=section,
            academic_year=academic_year,
            max_marks=max_marks,
            created_by=created_by
        )

        db.session.add(dt)
        db.session.commit()

    return dt


def dt_student_series(
    student_id,
    academic_year=ACADEMIC_YEAR
):
    """
    Returns DT1–DT6 performance for all six DT subjects.

    Example:

    {
        'English': [
            {
                'dt': 1,
                'marks': 20,
                'max': 25,
                'pct': 80,
                'class_avg_pct': 72,
                'date': ...
            }
        ]
    }
    """

    student = db.session.get(
        User,
        student_id
    )

    if not student:

        return {
            subject: []
            for subject in DT_SUBJECTS
        }

    series = {
        subject: []
        for subject in DT_SUBJECTS
    }

    for subject in DT_SUBJECTS:

        for dt_number in DT_NUMBERS:

            dt = DiagnosticTest.query.filter_by(
                dt_number=dt_number,
                subject=subject,
                grade=student.grade,
                academic_year=academic_year
            ).filter(
                db.or_(
                    DiagnosticTest.section == None,
                    DiagnosticTest.section == student.section
                )
            ).first()

            if not dt:

                series[subject].append({
                    'dt': dt_number,
                    'marks': None,
                    'max': None,
                    'pct': None,
                    'class_avg_pct': None,
                    'date': None
                })

                continue

            mark = DTMark.query.filter_by(
                dt_id=dt.id,
                student_id=student_id
            ).first()

            class_marks = [
                item.marks_obtained
                for item in dt.marks
            ]

            class_avg_pct = None

            if class_marks and dt.max_marks:

                class_avg_pct = round(
                    (
                        sum(class_marks)
                        /
                        len(class_marks)
                        /
                        dt.max_marks
                    ) * 100,
                    1
                )

            if mark:

                pct = (
                    round(
                        mark.marks_obtained
                        /
                        dt.max_marks
                        *
                        100,
                        1
                    )
                    if dt.max_marks
                    else 0
                )

                series[subject].append({
                    'dt': dt_number,
                    'marks': mark.marks_obtained,
                    'max': dt.max_marks,
                    'pct': pct,
                    'class_avg_pct': class_avg_pct,
                    'date': dt.test_date
                })

            else:

                series[subject].append({
                    'dt': dt_number,
                    'marks': None,
                    'max': dt.max_marks,
                    'pct': None,
                    'class_avg_pct': class_avg_pct,
                    'date': dt.test_date
                })

    return series


def dt_student_insights(series):

    insights = []

    for subject in DT_SUBJECTS:

        points = [
            point
            for point in series.get(subject, [])
            if point.get('pct') is not None
        ]

        values = [
            point['pct']
            for point in points
        ]

        average = (
            round(
                sum(values) / len(values),
                1
            )
            if values
            else None
        )

        trend = (
            round(
                values[-1] - values[0],
                1
            )
            if len(values) > 1
            else None
        )

        if average is not None and average >= 80:

            status = 'Strong'

        elif average is not None and average >= 60:

            status = 'Developing'

        elif average is not None:

            status = 'Needs focus'

        else:

            status = 'Not started'

        insights.append({
            'subject': subject,
            'average': average,
            'trend': trend,
            'completed': len(points),
            'latest': values[-1] if values else None,
            'status': status
        })

    return sorted(
        insights,
        key=lambda item: (
            item['average'] is None,
            item['average'] or 0
        )
    )


# =============================================================================
# PDF HEADER
# =============================================================================

def _pdf_header(
    c,
    title,
    subtitle
):

    width, height = A4

    c.setFillColorRGB(
        0.10,
        0.24,
        0.43
    )

    c.rect(
        0,
        height - 90,
        width,
        90,
        fill=1,
        stroke=0
    )

    c.setFillColorRGB(
        1,
        1,
        1
    )

    c.setFont(
        'Helvetica-Bold',
        18
    )

    c.drawString(
        40,
        height - 45,
        'Eastern Public School'
    )

    c.setFont(
        'Helvetica',
        11
    )

    c.drawString(
        40,
        height - 65,
        title
    )

    c.setFont(
        'Helvetica',
        9
    )

    c.drawString(
        40,
        height - 80,
        subtitle
    )

    c.setFillColorRGB(
        0,
        0,
        0
    )

    return height


def _dt_role_prefix():

    if session.get('role') == 'Resource_Manager':
        return 'admin'

    return 'teacher'


# =============================================================================
# DT MARK ENTRY
# =============================================================================

@app.route(
    '/teacher/dt',
    methods=['GET', 'POST'],
    endpoint='teacher_dt'
)
@app.route(
    '/admin/dt',
    methods=['GET', 'POST'],
    endpoint='admin_dt'
)
@login_required(
    ('teacher', 'Resource_Manager')
)
def dt_entry():

    if request.method == 'POST':

        grade = request.form['grade']

        section = (
            request.form.get('section')
            or None
        )

        subject = request.form['subject']

        dt_number = int(
            request.form['dt_number']
        )

        max_marks = float(
            request.form.get(
                'max_marks',
                25
            )
        )

        test_date = (
            request.form.get('test_date')
            or None
        )

        # IMPORTANT:
        # Academic year automatically becomes 2026-27.
        dt = dt_get_or_create(
            dt_number=dt_number,
            subject=subject,
            grade=grade,
            section=section,
            academic_year=ACADEMIC_YEAR,
            max_marks=max_marks,
            created_by=session['user_id']
        )

        dt.max_marks = max_marks

        if test_date:

            dt.test_date = datetime.strptime(
                test_date,
                '%Y-%m-%d'
            ).date()

        db.session.commit()

        student_ids = request.form.getlist(
            'student_id'
        )

        saved = 0

        for student_id in student_ids:

            value = request.form.get(
                f'marks_{student_id}',
                ''
            ).strip()

            if value == '':
                continue

            try:

                marks_value = float(value)

            except ValueError:

                continue

            # Prevent marks exceeding maximum.
            if marks_value < 0 or marks_value > max_marks:
                continue

            remark = request.form.get(
                f'remark_{student_id}',
                ''
            ).strip()

            existing = DTMark.query.filter_by(
                dt_id=dt.id,
                student_id=int(student_id)
            ).first()

            if existing:

                existing.marks_obtained = marks_value
                existing.remarks = remark
                existing.entered_by = session['user_id']
                existing.entered_at = datetime.utcnow()

            else:

                db.session.add(
                    DTMark(
                        dt_id=dt.id,
                        student_id=int(student_id),
                        marks_obtained=marks_value,
                        remarks=remark,
                        entered_by=session['user_id']
                    )
                )

            saved += 1

        db.session.commit()

        flash(
            f'Marks saved for {saved} student(s) — '
            f'{subject} DT{dt_number}, '
            f'{grade}'
            f'{" " + section if section else ""}',
            'success'
        )

        return redirect(
            url_for(
                f'{_dt_role_prefix()}_dt',
                grade=grade,
                section=section or '',
                subject=subject,
                dt_number=dt_number
            )
        )

    # -------------------------------------------------------------------------
    # GET
    # -------------------------------------------------------------------------

    grade = request.args.get(
        'grade',
        DT_GRADES[0]
    )

    section = request.args.get(
        'section',
        ''
    )

    subject = request.args.get(
        'subject',
        DT_SUBJECTS[0]
    )

    dt_number = int(
        request.args.get(
            'dt_number',
            1
        )
    )

    query = User.query.filter_by(
        role='student',
        grade=grade
    )

    if section:

        query = query.filter_by(
            section=section
        )

    students = query.order_by(
        User.name
    ).all()

    dt = DiagnosticTest.query.filter_by(
        dt_number=dt_number,
        subject=subject,
        grade=grade,
        section=section or None,
        academic_year=ACADEMIC_YEAR
    ).first()

    existing_marks = {}

    if dt:

        for mark in dt.marks:

            existing_marks[
                mark.student_id
            ] = {
                'marks': mark.marks_obtained,
                'remarks': mark.remarks or ''
            }

    return render_template(
        'dt/entry.html',

        students=students,

        # IMPORTANT:
        # Grade selector now contains Grade 1–5.
        grades=DT_GRADES,

        subjects=DT_SUBJECTS,
        dt_numbers=DT_NUMBERS,
        sections=DT_SECTIONS,

        grade=grade,
        section=section,
        subject=subject,
        dt_number=dt_number,

        dt=dt,
        existing_marks=existing_marks,

        academic_year=ACADEMIC_YEAR,

        role_prefix=_dt_role_prefix()
    )


# =============================================================================
# DT CSV UPLOAD
# =============================================================================

@app.route(
    '/teacher/dt/upload',
    methods=['GET', 'POST'],
    endpoint='teacher_dt_upload'
)
@app.route(
    '/admin/dt/upload',
    methods=['GET', 'POST'],
    endpoint='admin_dt_upload'
)
@login_required(
    ('teacher', 'Resource_Manager')
)
def dt_upload():

    grade = request.values.get(
        'grade',
        DT_GRADES[0]
    )

    section = request.values.get(
        'section',
        ''
    )

    subject = request.values.get(
        'subject',
        DT_SUBJECTS[0]
    )

    dt_number = int(
        request.values.get(
            'dt_number',
            1
        )
    )

    max_marks = float(
        request.values.get(
            'max_marks',
            25
        )
    )

    if request.method == 'POST':

        file = request.files.get(
            'csv_file'
        )

        if (
            not file
            or not file.filename.lower().endswith('.csv')
        ):

            flash(
                'Please upload a valid .csv file.',
                'error'
            )

            return redirect(
                url_for(
                    f'{_dt_role_prefix()}_dt_upload',
                    grade=grade,
                    section=section,
                    subject=subject,
                    dt_number=dt_number,
                    max_marks=max_marks
                )
            )

        dt = dt_get_or_create(
            dt_number=dt_number,
            subject=subject,
            grade=grade,
            section=section or None,
            academic_year=ACADEMIC_YEAR,
            max_marks=max_marks,
            created_by=session['user_id']
        )

        stream = io.StringIO(
            file.stream.read().decode(
                'utf-8-sig'
            )
        )

        reader = csv.DictReader(
            stream
        )

        added = 0
        skipped = 0

        for row in reader:

            username = row.get(
                'username',
                ''
            ).strip()

            marks_raw = row.get(
                'marks',
                ''
            ).strip()

            if not username or marks_raw == '':
                continue

            student = User.query.filter_by(
                username=username,
                role='student'
            ).first()

            if not student:

                skipped += 1
                continue

            try:

                marks_value = float(
                    marks_raw
                )

                if (
                    marks_value < 0
                    or marks_value > max_marks
                ):

                    skipped += 1
                    continue

            except ValueError:

                skipped += 1
                continue

            existing = DTMark.query.filter_by(
                dt_id=dt.id,
                student_id=student.id
            ).first()

            remarks = row.get(
                'remarks',
                ''
            ).strip()

            if existing:

                existing.marks_obtained = marks_value
                existing.remarks = remarks
                existing.entered_by = session['user_id']
                existing.entered_at = datetime.utcnow()

            else:

                db.session.add(
                    DTMark(
                        dt_id=dt.id,
                        student_id=student.id,
                        marks_obtained=marks_value,
                        remarks=remarks,
                        entered_by=session['user_id']
                    )
                )

            added += 1

        db.session.commit()

        flash(
            f'{added} marks uploaded '
            f'({skipped} skipped — check usernames/marks)',
            'success'
        )

        return redirect(
            url_for(
                f'{_dt_role_prefix()}_dt',
                grade=grade,
                section=section,
                subject=subject,
                dt_number=dt_number
            )
        )

    return render_template(
        'dt/upload.html',

        grade=grade,
        section=section,
        subject=subject,
        dt_number=dt_number,
        max_marks=max_marks,

        # IMPORTANT:
        grades=DT_GRADES,

        subjects=DT_SUBJECTS,
        dt_numbers=DT_NUMBERS,
        sections=DT_SECTIONS,

        academic_year=ACADEMIC_YEAR,

        role_prefix=_dt_role_prefix()
    )


# =============================================================================
# DT CSV TEMPLATE
# =============================================================================

@app.route(
    '/teacher/dt/upload-template',
    endpoint='teacher_dt_upload_template'
)
@app.route(
    '/admin/dt/upload-template',
    endpoint='admin_dt_upload_template'
)
@login_required(
    ('teacher', 'Resource_Manager')
)
def dt_upload_template():

    grade = request.args.get(
        'grade',
        ''
    )

    section = request.args.get(
        'section',
        ''
    )

    output = io.StringIO()

    writer = csv.writer(
        output
    )

    writer.writerow([
        'username',
        'marks',
        'remarks'
    ])

    query = User.query.filter_by(
        role='student'
    )

    if grade:

        query = query.filter_by(
            grade=grade
        )

    if section:

        query = query.filter_by(
            section=section
        )

    for student in query.order_by(
        User.name
    ).all():

        writer.writerow([
            student.username,
            '',
            ''
        ])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition':
            'attachment; filename=DT_marks_template.csv'
        }
    )


# =============================================================================
# DT GRAPH PAGE
# =============================================================================

@app.route(
    '/teacher/dt/graph',
    endpoint='teacher_dt_graph'
)
@app.route(
    '/admin/dt/graph',
    endpoint='admin_dt_graph'
)
@login_required(
    ('teacher', 'Resource_Manager')
)
def dt_graph():

    student_id = request.args.get(
        'student_id',
        type=int
    )

    grade = request.args.get(
        'grade',
        DT_GRADES[0]
    )

    section = request.args.get(
        'section',
        ''
    )

    query = User.query.filter_by(
        role='student',
        grade=grade
    )

    if section:

        query = query.filter_by(
            section=section
        )

    students = query.order_by(
        User.name
    ).all()

    sections = DT_SECTIONS

    series = None
    student = None

    if student_id:

        student = db.session.get(
            User,
            student_id
        )

        if student:

            series = dt_student_series(
                student_id
            )

    return render_template(
        'dt/graph.html',

        students=students,

        # Grade 1–5
        grades=DT_GRADES,

        sections=sections,

        grade=grade,
        section=section,

        student=student,
        series=series,

        subjects=DT_SUBJECTS,
        dt_numbers=DT_NUMBERS,

        academic_year=ACADEMIC_YEAR,

        role_prefix=_dt_role_prefix()
    )


# =============================================================================
# PARENT PDF — INDIVIDUAL DT RESULT + ALL DT GRAPH
# =============================================================================

@app.route(
    '/teacher/dt/pdf/<int:student_id>/<int:dt_number>',
    endpoint='teacher_dt_pdf_single'
)
@app.route(
    '/admin/dt/pdf/<int:student_id>/<int:dt_number>',
    endpoint='admin_dt_pdf_single'
)
@login_required(
    ('teacher', 'Resource_Manager')
)
def dt_pdf_single(
    student_id,
    dt_number
):

    student = db.session.get(
        User,
        student_id
    )

    if not student:

        flash(
            'Student not found.',
            'error'
        )

        return redirect(
            url_for(
                f'{_dt_role_prefix()}_dt'
            )
        )

    # -------------------------------------------------------------------------
    # Collect selected DT scores
    # -------------------------------------------------------------------------

    rows = []

    total_obtained = 0
    total_max = 0

    for subject in DT_SUBJECTS:

        dt = DiagnosticTest.query.filter_by(
            dt_number=dt_number,
            subject=subject,
            grade=student.grade,
            academic_year=ACADEMIC_YEAR
        ).filter(
            db.or_(
                DiagnosticTest.section == None,
                DiagnosticTest.section == student.section
            )
        ).first()

        if not dt:
            continue

        mark = DTMark.query.filter_by(
            dt_id=dt.id,
            student_id=student_id
        ).first()

        if not mark:
            continue

        percentage = (
            round(
                mark.marks_obtained
                /
                dt.max_marks
                *
                100,
                1
            )
            if dt.max_marks
            else 0
        )

        rows.append({
            'subject': subject,
            'marks': mark.marks_obtained,
            'max': dt.max_marks,
            'percentage': percentage,
            'remarks': mark.remarks or '',
            'date': dt.test_date
        })

        total_obtained += mark.marks_obtained
        total_max += dt.max_marks

    overall_pct = (
        round(
            total_obtained
            /
            total_max
            *
            100,
            1
        )
        if total_max
        else 0
    )

    # -------------------------------------------------------------------------
    # Get complete DT1–DT6 series for graph
    # -------------------------------------------------------------------------

    series = dt_student_series(
        student_id,
        academic_year=ACADEMIC_YEAR
    )

    # -------------------------------------------------------------------------
    # Create PDF
    # -------------------------------------------------------------------------

    buf = io.BytesIO()

    c = pdfcanvas.Canvas(
        buf,
        pagesize=A4
    )

    width, height = A4

    y = _pdf_header(
        c,
        f'Diagnostic Test {dt_number} — Student Progress',
        f'{student.grade}'
        f'{" " + student.section if student.section else ""}'
        f' · Academic Session {ACADEMIC_YEAR}'
    )

    # -------------------------------------------------------------------------
    # Student information
    # -------------------------------------------------------------------------

    c.setFillColorRGB(
        0,
        0,
        0
    )

    c.setFont(
        'Helvetica-Bold',
        12
    )

    c.drawString(
        40,
        y - 115,
        f'Student: {student.name}'
    )

    c.setFont(
        'Helvetica',
        10
    )

    c.drawString(
        40,
        y - 132,
        f'Grade: {student.grade}'
    )

    c.drawString(
        200,
        y - 132,
        f'Section: {student.section or "-"}'
    )

    c.drawString(
        350,
        y - 132,
        f'Diagnostic Test: DT{dt_number}'
    )

    # -------------------------------------------------------------------------
    # Selected DT score table
    # -------------------------------------------------------------------------

    table_y = y - 165

    c.setFillColorRGB(
        0.93,
        0.95,
        0.98
    )

    c.roundRect(
        40,
        table_y - 18,
        width - 80,
        28,
        4,
        fill=1,
        stroke=0
    )

    c.setFillColorRGB(
        0.10,
        0.15,
        0.25
    )

    c.setFont(
        'Helvetica-Bold',
        9
    )

    headers = [
        'Subject',
        'Marks',
        'Max',
        'Percentage',
        'Remarks'
    ]

    xpos = [
        50,
        220,
        285,
        350,
        440
    ]

    for header, x in zip(
        headers,
        xpos
    ):

        c.drawString(
            x,
            table_y - 8,
            header
        )

    table_y -= 38

    c.setFont(
        'Helvetica',
        9
    )

    if not rows:

        c.setFillColorRGB(
            0.45,
            0.45,
            0.45
        )

        c.drawString(
            50,
            table_y,
            'No marks recorded for this Diagnostic Test.'
        )

        table_y -= 25

    else:

        for row in rows:

            c.setFillColorRGB(
                0,
                0,
                0
            )

            c.drawString(
                50,
                table_y,
                row['subject']
            )

            c.drawString(
                220,
                table_y,
                str(row['marks'])
            )

            c.drawString(
                285,
                table_y,
                str(row['max'])
            )

            pct = row['percentage']

            if pct >= 80:

                c.setFillColorRGB(
                    0.06,
                    0.40,
                    0.20
                )

            elif pct >= 60:

                c.setFillColorRGB(
                    0.57,
                    0.25,
                    0.05
                )

            else:

                c.setFillColorRGB(
                    0.60,
                    0.12,
                    0.12
                )

            c.drawString(
                350,
                table_y,
                f"{pct}%"
            )

            c.setFillColorRGB(
                0,
                0,
                0
            )

            remark = row['remarks']

            if len(remark) > 22:
                remark = remark[:22] + '...'

            c.drawString(
                440,
                table_y,
                remark
            )

            table_y -= 20

    # -------------------------------------------------------------------------
    # Overall score
    # -------------------------------------------------------------------------

    table_y -= 5

    c.setFillColorRGB(
        0.10,
        0.24,
        0.43
    )

    c.roundRect(
        40,
        table_y - 5,
        width - 80,
        28,
        5,
        fill=1,
        stroke=0
    )

    c.setFillColorRGB(
        1,
        1,
        1
    )

    c.setFont(
        'Helvetica-Bold',
        10
    )

    c.drawString(
        52,
        table_y + 5,
        f'DT{dt_number} Overall: '
        f'{total_obtained:g}/{total_max:g}'
        f'  ({overall_pct}%)'
    )

    # -------------------------------------------------------------------------
    # PERFORMANCE GRAPH
    # -------------------------------------------------------------------------

    graph_top = table_y - 40

    c.setFillColorRGB(
        0,
        0,
        0
    )

    c.setFont(
        'Helvetica-Bold',
        11
    )

    c.drawString(
        40,
        graph_top,
        'Diagnostic Test Performance — DT1 to DT6'
    )

    graph = Drawing(
        width - 80,
        210
    )

    chart = HorizontalLineChart()

    chart.x = 35
    chart.y = 30

    chart.width = width - 150
    chart.height = 155

    chart.categoryAxis.categoryNames = [
        f'DT{n}'
        for n in DT_NUMBERS
    ]

    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 20

    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.labels.fontSize = 8

    chart.categoryAxis.visible = True
    chart.valueAxis.visible = True

    # IMPORTANT:
    # Use all six DT subjects.
    for subject in DT_SUBJECTS:

        points = []

        for point in series.get(
            subject,
            []
        ):

            if point['pct'] is None:
                points.append(None)
            else:
                points.append(point['pct'])

        while len(points) < 6:
            points.append(None)

        # ReportLab line charts don't like None in every situation,
        # so only use 0 for missing points.
        clean_points = [
            value if value is not None else 0
            for value in points[:6]
        ]

        chart.data.append(
            clean_points
        )

    # Six separate lines
    for index in range(
        len(DT_SUBJECTS)
    ):

        chart.lines[
            index
        ].strokeWidth = 1.8

    graph.add(
        chart
    )

    renderPDF.draw(
        graph,
        c,
        40,
        graph_top - 215
    )

    # -------------------------------------------------------------------------
    # Graph legend
    # -------------------------------------------------------------------------

    legend_y = graph_top - 230

    c.setFont(
        'Helvetica',
        7.5
    )

    legend_x = 45

    for subject in DT_SUBJECTS:

        c.setFillColorRGB(
            0.15,
            0.25,
            0.50
        )

        c.rect(
            legend_x,
            legend_y,
            7,
            7,
            fill=1,
            stroke=0
        )

        c.setFillColorRGB(
            0,
            0,
            0
        )

        c.drawString(
            legend_x + 10,
            legend_y,
            subject
        )

        legend_x += 82

        if legend_x > width - 100:

            legend_x = 45
            legend_y -= 14

    # -------------------------------------------------------------------------
    # Footer
    # -------------------------------------------------------------------------

    c.setFillColorRGB(
        0.45,
        0.45,
        0.45
    )

    c.setFont(
        'Helvetica-Oblique',
        7.5
    )

    c.drawString(
        40,
        35,
        f'Academic Session {ACADEMIC_YEAR} · '
        'Eastern Public School · '
        'Diagnostic Test Progress Report'
    )

    c.drawRightString(
        width - 40,
        35,
        f'Generated: {datetime.utcnow().strftime("%d %b %Y")}'
    )

    c.showPage()
    c.save()

    buf.seek(0)

    safe_name = re.sub(
        r'[^A-Za-z0-9_-]+',
        '_',
        student.name
    )

    filename = (
        f'DT{dt_number}_'
        f'{safe_name}_'
        f'{ACADEMIC_YEAR.replace("-", "_")}.pdf'
    )

    return Response(
        buf.read(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition':
            f'attachment; filename="{filename}"'
        }
    )


# =============================================================================
# COMPLETE DT PROGRESS REPORT
# =============================================================================

@app.route(
    '/teacher/dt/report/<int:student_id>',
    endpoint='teacher_dt_report'
)
@app.route(
    '/admin/dt/report/<int:student_id>',
    endpoint='admin_dt_report'
)
@login_required(
    ('teacher', 'Resource_Manager')
)
def dt_report(student_id):

    student = db.session.get(
        User,
        student_id
    )

    if not student:

        flash(
            'Student not found.',
            'error'
        )

        return redirect(
            url_for(
                f'{_dt_role_prefix()}_dt'
            )
        )

    series = dt_student_series(
        student_id,
        academic_year=ACADEMIC_YEAR
    )

    buf = io.BytesIO()

    c = pdfcanvas.Canvas(
        buf,
        pagesize=A4
    )

    width, height = A4

    y = _pdf_header(
        c,
        'Diagnostic Test — Progress Report',
        f'{student.grade}'
        f'{" " + student.section if student.section else ""}'
        f' · Academic Session {ACADEMIC_YEAR}'
    )

    c.setFont(
        'Helvetica-Bold',
        12
    )

    c.drawString(
        40,
        y - 115,
        f'Student: {student.name}'
    )

    c.setFont(
        'Helvetica',
        10
    )

    c.drawString(
        40,
        y - 132,
        f'Grade: {student.grade}'
    )

    c.drawString(
        180,
        y - 132,
        f'Section: {student.section or "-"}'
    )

    c.drawString(
        300,
        y - 132,
        f'Session: {ACADEMIC_YEAR}'
    )

    # -------------------------------------------------------------------------
    # Graph
    # -------------------------------------------------------------------------

    d = Drawing(
        width - 80,
        215
    )

    chart = HorizontalLineChart()

    chart.x = 30
    chart.y = 25

    chart.width = width - 150
    chart.height = 160

    chart.categoryAxis.categoryNames = [
        f'DT{n}'
        for n in DT_NUMBERS
    ]

    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 20

    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.labels.fontSize = 8

    # ALL SIX SUBJECTS
    for subject in DT_SUBJECTS:

        values = []

        for point in series[subject]:

            if point['pct'] is None:
                values.append(0)
            else:
                values.append(point['pct'])

        while len(values) < 6:
            values.append(0)

        chart.data.append(
            values[:6]
        )

    for i in range(
        len(DT_SUBJECTS)
    ):

        chart.lines[
            i
        ].strokeWidth = 2

    d.add(
        chart
    )

    renderPDF.draw(
        d,
        c,
        40,
        y - 345
    )

    # -------------------------------------------------------------------------
    # Legend
    # -------------------------------------------------------------------------

    legend_x = 45
    legend_y = y - 365

    c.setFont(
        'Helvetica',
        7.5
    )

    for subject in DT_SUBJECTS:

        c.setFillColorRGB(
            0.15,
            0.25,
            0.50
        )

        c.rect(
            legend_x,
            legend_y,
            7,
            7,
            fill=1,
            stroke=0
        )

        c.setFillColorRGB(
            0,
            0,
            0
        )

        c.drawString(
            legend_x + 10,
            legend_y,
            subject
        )

        legend_x += 80

        if legend_x > width - 100:

            legend_x = 45
            legend_y -= 14

    # -------------------------------------------------------------------------
    # DT table
    # -------------------------------------------------------------------------

    ty = y - 405

    c.setFont(
        'Helvetica-Bold',
        10
    )

    c.drawString(
        40,
        ty,
        'DT-wise Performance (%)'
    )

    ty -= 20

    c.setFont(
        'Helvetica-Bold',
        7.5
    )

    headers = [
        'Subject'
    ] + [
        f'DT{n}'
        for n in DT_NUMBERS
    ] + [
        'Average'
    ]

    xpos = [
        40,
        115,
        155,
        195,
        235,
        275,
        315,
        370
    ]

    for header, x in zip(
        headers,
        xpos
    ):

        c.drawString(
            x,
            ty,
            header
        )

    ty -= 15

    c.setFont(
        'Helvetica',
        7.5
    )

    for subject in DT_SUBJECTS:

        c.drawString(
            40,
            ty,
            subject
        )

        values = []

        for i in range(6):

            if i < len(
                series[subject]
            ):

                pct = series[
                    subject
                ][i]['pct']

            else:

                pct = None

            if pct is not None:

                c.drawString(
                    xpos[i + 1],
                    ty,
                    f'{pct}%'
                )

                values.append(
                    pct
                )

            else:

                c.drawString(
                    xpos[i + 1],
                    ty,
                    '—'
                )

        average = (
            round(
                sum(values) / len(values),
                1
            )
            if values
            else 0
        )

        c.setFont(
            'Helvetica-Bold',
            7.5
        )

        c.drawString(
            xpos[-1],
            ty,
            f'{average}%'
        )

        c.setFont(
            'Helvetica',
            7.5
        )

        ty -= 15

    # -------------------------------------------------------------------------
    # Footer
    # -------------------------------------------------------------------------

    c.setFont(
        'Helvetica-Oblique',
        7.5
    )

    c.setFillColorRGB(
        0.5,
        0.5,
        0.5
    )

    c.drawString(
        40,
        35,
        f'Academic Session {ACADEMIC_YEAR} · '
        'Eastern Public School IBT Portal'
    )

    c.drawRightString(
        width - 40,
        35,
        f'Generated {datetime.utcnow().strftime("%d %b %Y")}'
    )

    c.showPage()
    c.save()

    buf.seek(0)

    filename = (
        'DT_Progress_Report_'
        f'{re.sub(r"[^A-Za-z0-9_-]+", "_", student.name)}_'
        f'{ACADEMIC_YEAR.replace("-", "_")}.pdf'
    )

    return Response(
        buf.read(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition':
            f'attachment; filename="{filename}"'
        }
    )


# =============================================================================
# STUDENT DIAGNOSTICS
# =============================================================================

@app.route(
    '/student/diagnostics'
)
@login_required('student')
def student_diagnostics():

    student = db.session.get(
        User,
        session['user_id']
    )

    series = dt_student_series(
        student.id,
        academic_year=ACADEMIC_YEAR
    )

    insights = dt_student_insights(
        series
    )

    weak_subjects = [
        item['subject']
        for item in insights
        if (
            item['average'] is not None
            and item['average'] < 80
        )
    ]

    practice_tests = MockTest.query.filter(
        MockTest.status == 'active',
        db.or_(
            MockTest.grade == student.grade,
            MockTest.grade == 'All Grades'
        )
    ).order_by(
        MockTest.subject,
        MockTest.name
    ).all()

    return render_template(
        'student/diagnostics.html',

        student=student,

        series=series,

        insights=insights,

        subjects=DT_SUBJECTS,

        dt_numbers=DT_NUMBERS,

        weak_subjects=weak_subjects,

        practice_tests=practice_tests,

        academic_year=ACADEMIC_YEAR
    )


# =============================================================================
# DATABASE INITIALIZATION
# =============================================================================

with app.app_context():

    db.create_all()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':

    print(
        'Eastern Public School — IBT Portal'
    )

    print(
        f'Academic Session: {ACADEMIC_YEAR}'
    )

    print(
        'Diagnostic Tests: Grades 1–5'
    )

    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000
    )
