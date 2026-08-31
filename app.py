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

# ── IB CONSTANTS ──────────────────────────────────────────────────────────────
TERMS = ['Term 1', 'Term 2', 'Term 3']
RATING_SCALE = {1: 'Beginning', 2: 'Developing', 3: 'Achieved', 4: 'Exceeding'}
RATING_COLORS = {1: '#ef4444', 2: '#f59e0b', 3: '#3b82f6', 4: '#10b981'}

LEARNER_PROFILE = [
    ('Inquirer',      'Nurtures curiosity and love of learning. Acquires skills to inquire and research independently.'),
    ('Knowledgeable', 'Explores concepts across disciplines. Engages with local and global issues.'),
    ('Thinker',       'Uses critical and creative thinking to tackle complex problems and make ethical decisions.'),
    ('Communicator',  'Expresses ideas confidently in multiple modes and collaborates effectively.'),
    ('Principled',    'Acts with integrity and honesty. Takes responsibility for actions and consequences.'),
    ('Open-minded',   'Appreciates own and others cultures. Seeks and evaluates diverse perspectives.'),
    ('Caring',        'Shows empathy, compassion and respect. Makes a positive difference to others.'),
    ('Risk-taker',    'Approaches uncertainty with courage and creativity. Explores new ideas and strategies.'),
    ('Balanced',      'Understands importance of intellectual, physical and emotional balance.'),
    ('Reflective',    'Thoughtfully considers learning and experiences to improve understanding and growth.'),
]

ATL_SKILLS = {
    'Communication': {
        'Grade 3': ['Shares ideas clearly in class discussions','Listens attentively when others speak','Writes sentences with a clear beginning and end','Reads aloud with expression and understanding'],
        'Grade 4': ['Expresses ideas using appropriate vocabulary','Asks clarifying questions during discussions','Organises written work with introduction and conclusion','Reads and summarises key information'],
        'Grade 5': ['Communicates effectively for different audiences','Evaluates and responds to others ideas respectfully','Writes structured arguments with evidence','Analyses texts and identifies authors purpose'],
    },
    'Self-Management': {
        'Grade 3': ['Brings required materials to class','Follows classroom routines independently','Manages time during tasks with teacher support','Stays on task with minimal reminders'],
        'Grade 4': ['Organises work and materials independently','Sets personal goals with teacher guidance','Manages time effectively during class activities','Reflects on learning with prompting'],
        'Grade 5': ['Plans and organises multi-step tasks independently','Sets and monitors personal learning goals','Manages time across multiple responsibilities','Reflects critically on own learning and progress'],
    },
    'Research': {
        'Grade 3': ['Identifies information from given sources','Distinguishes between fact and opinion with support','Records information in own words','Uses library and digital resources with guidance'],
        'Grade 4': ['Selects relevant information from multiple sources','Identifies reliable vs unreliable sources','Organises research notes effectively','Cites sources with teacher support'],
        'Grade 5': ['Independently researches using varied sources','Evaluates credibility and bias in sources','Synthesises information to form conclusions','Properly attributes sources and avoids plagiarism'],
    },
    'Thinking': {
        'Grade 3': ['Makes connections between new and prior learning','Identifies patterns and sequences','Generates ideas during brainstorming','Solves simple problems with support'],
        'Grade 4': ['Asks why and what if questions','Applies knowledge to new situations','Identifies cause and effect relationships','Evaluates solutions to problems'],
        'Grade 5': ['Analyses information from multiple perspectives','Creates original solutions to complex problems','Transfers learning across subjects','Justifies reasoning with evidence'],
    },
    'Social': {
        'Grade 3': ['Takes turns and shares during group activities','Shows kindness and respect to classmates','Accepts different roles in group work','Resolves conflicts with teacher support'],
        'Grade 4': ['Contributes meaningfully to group discussions','Encourages and supports peers','Adapts role based on group needs','Resolves minor conflicts independently'],
        'Grade 5': ['Leads and participates effectively in groups','Considers diverse perspectives in collaboration','Negotiates and compromises to achieve goals','Mediates conflicts constructively'],
    },
}
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

# ── IB HOLISTIC MODELS ───────────────────────────────────────────────────────

ATL_SKILLS = {
    'Communication':    ['Reading & Writing', 'Listening & Speaking', 'Presenting Ideas'],
    'Self-Management':  ['Organisation', 'Time Management', 'Reflection'],
    'Research':         ['Information Literacy', 'Media Literacy', 'Using Sources'],
    'Thinking':         ['Critical Thinking', 'Creative Thinking', 'Problem Solving'],
    'Social':           ['Collaboration', 'Respecting Others', 'Leadership'],
}

LEARNER_PROFILE = [
    'Inquirer', 'Knowledgeable', 'Thinker', 'Communicator', 'Principled',
    'Open-minded', 'Caring', 'Risk-taker', 'Balanced', 'Reflective'
]

LP_DESCRIPTIONS = {
    'Inquirer':      'Nurtures curiosity and love of learning',
    'Knowledgeable': 'Explores concepts across disciplines',
    'Thinker':       'Uses critical and creative thinking skills',
    'Communicator':  'Expresses ideas confidently in many ways',
    'Principled':    'Acts with integrity and honesty',
    'Open-minded':   'Appreciates other perspectives and cultures',
    'Caring':        'Shows empathy, compassion and respect',
    'Risk-taker':    'Approaches uncertainty with courage',
    'Balanced':      'Understands importance of all aspects of life',
    'Reflective':    'Thoughtfully considers own learning and growth',
}

ATL_DESCRIPTORS = {
    'Grade 3': {
        1: 'I am just starting to learn this skill',
        2: 'I sometimes use this skill with help',
        3: 'I often use this skill on my own',
        4: 'I always use this skill and help my friends',
    },
    'Grade 4': {
        1: 'I am aware of this skill but need reminders',
        2: 'I use this skill sometimes with support',
        3: 'I independently use this skill most of the time',
        4: 'I consistently use and model this skill for others',
    },
    'Grade 5': {
        1: 'I am beginning to develop this skill with guidance',
        2: 'I apply this skill in familiar situations with some support',
        3: 'I consistently apply this skill across different contexts',
        4: 'I demonstrate this skill with sophistication and mentor peers',
    },
}

LP_DESCRIPTORS = {
    'Grade 3': {1:'Just starting',  2:'Sometimes',  3:'Often',        4:'Always'},
    'Grade 4': {1:'Beginning',      2:'Developing', 3:'Achieved',     4:'Exceeding'},
    'Grade 5': {1:'Beginning',      2:'Developing', 3:'Consistently', 4:'Exemplary'},
}

TERMS = ['Term 1', 'Term 2', 'Term 3']


class ATLRating(db.Model):
    __tablename__ = 'atl_rating'
    id           = db.Column(db.Integer, primary_key=True)
    student_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rater_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rater_type   = db.Column(db.String(10), nullable=False)  # 'teacher' or 'student'
    term         = db.Column(db.String(20), nullable=False)
    category     = db.Column(db.String(50), nullable=False)
    skill        = db.Column(db.String(100), nullable=False)
    rating       = db.Column(db.Integer, nullable=False)  # 1-4
    comment      = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    student      = db.relationship('User', foreign_keys=[student_id])
    rater        = db.relationship('User', foreign_keys=[rater_id])


class LearnerProfileRating(db.Model):
    __tablename__ = 'lp_rating'
    id           = db.Column(db.Integer, primary_key=True)
    student_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rater_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rater_type   = db.Column(db.String(10), nullable=False)  # 'teacher' or 'student'
    term         = db.Column(db.String(20), nullable=False)
    attribute    = db.Column(db.String(50), nullable=False)
    rating       = db.Column(db.Integer, nullable=False)  # 1-4
    evidence     = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    student      = db.relationship('User', foreign_keys=[student_id])
    rater        = db.relationship('User', foreign_keys=[rater_id])


class StudentReflection(db.Model):
    __tablename__ = 'student_reflection'
    id           = db.Column(db.Integer, primary_key=True)
    student_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    term         = db.Column(db.String(20), nullable=False)
    reflection   = db.Column(db.Text, nullable=False)
    goals        = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    student      = db.relationship('User', foreign_keys=[student_id])


# ── IB HOLISTIC MODELS ───────────────────────────────────────────────────────

ATL_SKILLS = {
    'Communication':   ['Exchanges information clearly','Listens actively','Reads with understanding','Writes effectively','Presents ideas confidently'],
    'Self-Management': ['Organises time and tasks','Manages materials','Reflects on learning','Shows perseverance','Sets goals'],
    'Research':        ['Finds reliable information','Evaluates sources','Documents information','Uses data effectively'],
    'Thinking':        ['Thinks critically','Thinks creatively','Transfers knowledge','Solves problems','Makes connections'],
    'Social':          ['Collaborates respectfully','Supports peers','Manages disagreements','Contributes to group'],
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

LEARNER_PROFILE = [
    ('Inquirer',     '🔍', 'Nurtures curiosity and love of learning'),
    ('Knowledgeable','📚', 'Develops conceptual understanding across disciplines'),
    ('Thinker',      '💡', 'Applies critical and creative thinking skills'),
    ('Communicator', '🗣️', 'Expresses ideas confidently in multiple modes'),
    ('Principled',   '⚖️', 'Acts with integrity, honesty and strong ethics'),
    ('Open-minded',  '🌍', 'Appreciates perspectives, cultures and ideas'),
    ('Caring',       '❤️', 'Shows empathy, compassion and respect for others'),
    ('Risk-taker',   '🚀', 'Approaches uncertainty with courage and forethought'),
    ('Balanced',     '⚖️', 'Understands importance of balance in all life areas'),
    ('Reflective',   '🪞', 'Thoughtfully considers learning and personal growth'),
]

TERMS = ['Term 1', 'Term 2', 'Term 3']


# ── IB DEVELOPMENT MODELS ────────────────────────────────────────────────────

# ATL descriptors per grade and skill
ATL_SKILLS = {
    'Communication': {
        'Grade 3': ['Listens attentively during discussions', 'Expresses ideas clearly in writing', 'Uses appropriate vocabulary', 'Participates in group activities'],
        'Grade 4': ['Organises ideas logically in writing', 'Listens and responds thoughtfully', 'Uses subject-specific vocabulary', 'Presents information to an audience'],
        'Grade 5': ['Communicates complex ideas persuasively', 'Adapts communication style for audience', 'Uses evidence to support arguments', 'Gives and receives constructive feedback'],
    },
    'Self-Management': {
        'Grade 3': ['Follows classroom routines independently', 'Completes tasks within given time', 'Keeps materials organised', 'Manages emotions appropriately'],
        'Grade 4': ['Sets personal learning goals', 'Plans and prioritises tasks', 'Reflects on own learning', 'Manages distractions effectively'],
        'Grade 5': ['Develops strategies to overcome challenges', 'Monitors own progress toward goals', 'Demonstrates perseverance', 'Balances responsibilities effectively'],
    },
    'Research': {
        'Grade 3': ['Asks relevant questions', 'Locates information from given sources', 'Records findings in own words', 'Identifies fact vs. opinion'],
        'Grade 4': ['Selects appropriate sources', 'Evaluates reliability of information', 'Takes organised notes', 'Cites sources used'],
        'Grade 5': ['Formulates focused research questions', 'Critically evaluates multiple sources', 'Synthesises information effectively', 'Acknowledges intellectual property'],
    },
    'Thinking': {
        'Grade 3': ['Makes connections between ideas', 'Identifies patterns and relationships', 'Offers creative solutions', 'Asks "why" and "what if" questions'],
        'Grade 4': ['Analyses cause and effect', 'Evaluates different perspectives', 'Applies knowledge to new situations', 'Justifies opinions with reasons'],
        'Grade 5': ['Evaluates arguments critically', 'Generates and tests hypotheses', 'Transfers learning across subjects', 'Reflects on thinking processes (metacognition)'],
    },
    'Social': {
        'Grade 3': ['Takes turns and shares fairly', 'Respects different opinions', 'Helps classmates when needed', 'Follows agreed group rules'],
        'Grade 4': ['Contributes meaningfully to group work', 'Resolves conflicts respectfully', 'Encourages others', 'Takes on different group roles'],
        'Grade 5': ['Leads and supports team efforts', 'Negotiates and compromises effectively', 'Advocates for others', "Builds on others ideas constructively"],
    },
}

IB_LEARNER_PROFILE = [
    ('Inquirer',     '🔍', 'Nurtures curiosity, developing skills for inquiry and research'),
    ('Knowledgeable','📚', 'Explores concepts across disciplines with depth and breadth'),
    ('Thinker',      '💡', 'Uses critical and creative thinking to tackle complex problems'),
    ('Communicator', '🗣️', 'Expresses ideas confidently in more than one language'),
    ('Principled',   '⚖️', 'Acts with integrity, honesty and a strong sense of fairness'),
    ('Open-minded',  '🌍', 'Appreciates own culture and perspectives of others'),
    ('Caring',       '❤️', 'Shows empathy, compassion and respect for others'),
    ('Risk-taker',   '🚀', 'Approaches uncertainty with courage and forethought'),
    ('Balanced',     '⚖️', 'Understands importance of physical, mental and emotional balance'),
    ('Reflective',   '🪞', 'Thoughtfully considers learning and personal development'),
]

RATING_LABELS = {1: 'Beginning', 2: 'Developing', 3: 'Achieved', 4: 'Exceeding'}
TERMS = ['Term 1', 'Term 2', 'Term 3']


# ── IB DEVELOPMENT MODELS ────────────────────────────────────────────────────

ATL_CATEGORIES = {
    'Communication':   ['Reading & Writing', 'Listening & Speaking', 'Presenting Ideas'],
    'Self-Management': ['Organisation', 'Time Management', 'Emotional Regulation'],
    'Research':        ['Finding Information', 'Evaluating Sources', 'Recording Data'],
    'Thinking':        ['Critical Thinking', 'Creative Thinking', 'Problem Solving'],
    'Social':          ['Collaboration', 'Respecting Others', 'Conflict Resolution'],
}

LEARNER_PROFILE = [
    ('Inquirer',      '🔍', 'Develops curiosity and love of learning'),
    ('Knowledgeable', '📚', 'Explores concepts across disciplines'),
    ('Thinker',       '💡', 'Applies critical and creative thinking'),
    ('Communicator',  '🗣️', 'Expresses ideas confidently'),
    ('Principled',    '⚖️', 'Acts with integrity and honesty'),
    ('Open-minded',   '🌍', 'Appreciates other perspectives'),
    ('Caring',        '❤️', 'Shows empathy and compassion'),
    ('Risk-taker',    '🚀', 'Approaches uncertainty with courage'),
    ('Balanced',      '⚡', 'Balances intellectual and personal growth'),
    ('Reflective',    '🪞', 'Thoughtfully considers own learning'),
]

ATL_DESCRIPTORS = {
    'Grade 3': {
        1: 'Beginning — Needs significant support',
        2: 'Developing — Shows some understanding with guidance',
        3: 'Achieved — Demonstrates skill independently',
        4: 'Exceeding — Models skill and supports peers',
    },
    'Grade 4': {
        1: 'Beginning — Rarely demonstrates the skill',
        2: 'Developing — Sometimes demonstrates with prompting',
        3: 'Achieved — Consistently demonstrates the skill',
        4: 'Exceeding — Extends and applies skill in new contexts',
    },
    'Grade 5': {
        1: 'Beginning — Limited awareness of the skill',
        2: 'Developing — Growing awareness, inconsistent application',
        3: 'Achieved — Confident and consistent application',
        4: 'Exceeding — Exemplary — leads and inspires others',
    },
}

TERMS = ['Term 1', 'Term 2', 'Term 3']
ACADEMIC_YEAR = '2025-26'


# ── IB DEVELOPMENT MODELS ────────────────────────────────────────────────────

TERMS = ['Term 1', 'Term 2', 'Term 3']

LEARNER_PROFILE = [
    ('inquirer',    '🔍 Inquirer',     'Nurtures curiosity, develops skills for inquiry and research'),
    ('knowledgeable','📚 Knowledgeable','Develops and uses conceptual understanding across disciplines'),
    ('thinker',     '💭 Thinker',      'Uses critical and creative thinking to analyse complex problems'),
    ('communicator','💬 Communicator', 'Expresses confidently in more than one language and in many ways'),
    ('principled',  '⚖️ Principled',   'Acts with integrity and honesty, with strong sense of fairness'),
    ('open_minded', '🌍 Open-minded',  'Appreciates own culture and others, seeks diverse perspectives'),
    ('caring',      '❤️ Caring',       'Shows empathy, compassion and respect, makes a positive difference'),
    ('risk_taker',  '🚀 Risk-taker',   'Approaches uncertainty with forethought and determination'),
    ('balanced',    '⚖️ Balanced',     'Understands importance of intellectual, physical and emotional balance'),
    ('reflective',  '🪞 Reflective',   'Thoughtfully considers the world and own ideas and experience'),
]

ATL_CATEGORIES = {
    'communication': {
        'label': '💬 Communication',
        'skills': ['Reading & Writing', 'Listening & Speaking', 'Digital Communication'],
        'descriptors': {
            'Grade 3': {
                1: 'Rarely communicates ideas clearly',
                2: 'Sometimes shares ideas with support',
                3: 'Usually communicates ideas clearly',
                4: 'Always communicates ideas clearly and confidently',
            },
            'Grade 4': {
                1: 'Struggles to express ideas in writing or speech',
                2: 'Expresses basic ideas with some support',
                3: 'Expresses ideas clearly in writing and speech',
                4: 'Expresses ideas with clarity, detail and confidence',
            },
            'Grade 5': {
                1: 'Has difficulty structuring ideas for different audiences',
                2: 'Communicates ideas with inconsistent structure',
                3: 'Communicates effectively for purpose and audience',
                4: 'Communicates with sophistication adapting to any context',
            },
        }
    },
    'self_management': {
        'label': '🗂️ Self-Management',
        'skills': ['Organisation', 'Time Management', 'Emotional Regulation'],
        'descriptors': {
            'Grade 3': {
                1: 'Needs constant reminders to stay organised',
                2: 'Sometimes organises tasks with reminders',
                3: 'Usually organises work and meets deadlines',
                4: 'Consistently self-organised and meets all deadlines',
            },
            'Grade 4': {
                1: 'Rarely manages time or materials independently',
                2: 'Manages time with frequent teacher support',
                3: 'Manages time and materials independently',
                4: 'Excellently manages time, materials and emotions',
            },
            'Grade 5': {
                1: 'Struggles to set goals or monitor own learning',
                2: 'Sets goals but rarely follows through consistently',
                3: 'Sets and works toward goals with reflection',
                4: 'Independently sets, monitors and achieves goals',
            },
        }
    },
    'research': {
        'label': '🔎 Research',
        'skills': ['Information Literacy', 'Media Literacy', 'Note-taking'],
        'descriptors': {
            'Grade 3': {
                1: 'Rarely finds or uses information independently',
                2: 'Finds information with significant guidance',
                3: 'Finds and uses relevant information with some guidance',
                4: 'Independently researches and evaluates information',
            },
            'Grade 4': {
                1: 'Cannot distinguish reliable from unreliable sources',
                2: 'Sometimes identifies reliable sources with help',
                3: 'Usually selects reliable and relevant sources',
                4: 'Consistently evaluates and synthesises quality sources',
            },
            'Grade 5': {
                1: 'Rarely questions or evaluates information sources',
                2: 'Begins to question sources with teacher prompting',
                3: 'Questions sources and identifies bias',
                4: 'Critically evaluates sources for bias, purpose and reliability',
            },
        }
    },
    'thinking': {
        'label': '💡 Thinking',
        'skills': ['Critical Thinking', 'Creative Thinking', 'Transfer'],
        'descriptors': {
            'Grade 3': {
                1: 'Rarely applies prior knowledge to new tasks',
                2: 'Sometimes connects ideas with teacher support',
                3: 'Often makes connections between ideas',
                4: 'Consistently applies thinking across contexts',
            },
            'Grade 4': {
                1: 'Struggles to generate ideas or solutions independently',
                2: 'Generates basic ideas with guidance',
                3: 'Generates creative and logical ideas independently',
                4: 'Consistently generates innovative, well-reasoned ideas',
            },
            'Grade 5': {
                1: 'Rarely analyses or evaluates complex problems',
                2: 'Begins to analyse problems with support',
                3: 'Analyses problems and proposes reasoned solutions',
                4: 'Critically analyses and evaluates with depth and nuance',
            },
        }
    },
    'social': {
        'label': '🤝 Social',
        'skills': ['Collaboration', 'Conflict Resolution', 'Respect for Others'],
        'descriptors': {
            'Grade 3': {
                1: 'Rarely works cooperatively in groups',
                2: 'Sometimes cooperates with reminders',
                3: 'Usually cooperates and contributes to group work',
                4: 'Always contributes positively and supports peers',
            },
            'Grade 4': {
                1: "Struggles to listen to or consider others views",
                2: 'Sometimes listens and considers others with support',
                3: 'Listens actively and considers diverse perspectives',
                4: 'Champions inclusion and mediates group conflict positively',
            },
            'Grade 5': {
                1: 'Rarely takes shared responsibility in collaborative tasks',
                2: 'Takes limited responsibility in collaborative tasks',
                3: 'Takes responsibility and supports team goals',
                4: 'Leads and inspires effective collaboration',
            },
        }
    },
}

RATING_LABELS = {1: 'Beginning', 2: 'Developing', 3: 'Achieved', 4: 'Exceeding'}
RATING_COLORS = {1: '#fee2e2', 2: '#fef9c3', 3: '#dcfce7', 4: '#dbeafe'}
RATING_TEXT   = {1: '#dc2626', 2: '#92400e', 3: '#166534', 4: '#1d4ed8'}


# ── IB HOLISTIC MODELS ───────────────────────────────────────────────────────

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

def build_analytics(filter_grade=None, filter_section=None, filter_subject=None):
    students    = User.query.filter_by(role='student').all()
    all_results = TestResult.query.all()

    # Apply filters
    if filter_grade:
        all_results = [r for r in all_results if r.student.grade == filter_grade]
        students    = [s for s in students if s.grade == filter_grade]
    if filter_section:
        all_results = [r for r in all_results if r.student.section == filter_section]
        students    = [s for s in students if s.section == filter_section]
    if filter_subject:
        all_results = [r for r in all_results if r.test.subject == filter_subject]

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

    # Strand-wise breakdown PER SUBJECT
    subject_strands = {}
    for sub in SUBJECTS:
        sub_results = [r for r in all_results if r.test.subject == sub]
        strand_data = {}
        for r in sub_results:
            try:
                secs = json.loads(r.section_scores or '{}')
                for sec, v in secs.items():
                    if v['total'] > 0:
                        pct = round(v['correct']/v['total']*100, 1)
                        strand_data.setdefault(sec, []).append(pct)
            except Exception:
                pass
        subject_strands[sub] = {sec: safe_avg(vals) for sec, vals in strand_data.items()}

    # Overall section avgs
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
        subject_strands=subject_strands,
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
    filter_grade   = request.args.get('grade', '')
    filter_section = request.args.get('section', '')
    filter_subject = request.args.get('subject', '')
    data = build_analytics(
        filter_grade   = filter_grade   or None,
        filter_section = filter_section or None,
        filter_subject = filter_subject or None,
    )
    data['filter_grade']   = filter_grade
    data['filter_section'] = filter_section
    data['filter_subject'] = filter_subject
    data['sections']       = ['A','B','C','D']
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


# ── IB HOLISTIC ROUTES ───────────────────────────────────────────────────────

# ── Teacher: ATL Rating ───────────────────────────────────────────────────────
@app.route('/ib/atl', methods=['GET','POST'])
@login_required('Resource_Manager')
def ib_atl_admin():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    selected_student = None
    selected_term = request.args.get('term', 'Term 1')
    student_id = request.args.get('student_id', type=int)
    existing_ratings = {}
    if student_id:
        selected_student = db.session.get(User, student_id)
        ratings = ATLRating.query.filter_by(
            student_id=student_id, term=selected_term, rater_type='teacher'
        ).all()
        for r in ratings:
            existing_ratings[f"{r.category}|{r.skill}"] = {'rating': r.rating, 'comment': r.comment or ''}
    if request.method == 'POST':
        sid   = int(request.form.get('student_id'))
        term  = request.form.get('term')
        student = db.session.get(User, sid)
        for cat, skills in ATL_SKILLS.items():
            for skill in skills:
                key = f"{cat}|{skill}"
                rating_val = request.form.get(f'rating_{key}', type=int)
                comment    = request.form.get(f'comment_{key}', '').strip()
                if rating_val:
                    existing = ATLRating.query.filter_by(
                        student_id=sid, term=term, category=cat,
                        skill=skill, rater_type='teacher'
                    ).first()
                    if existing:
                        existing.rating = rating_val
                        existing.comment = comment
                    else:
                        db.session.add(ATLRating(
                            student_id=sid, rater_id=session['user_id'],
                            rater_type='teacher', term=term,
                            category=cat, skill=skill,
                            rating=rating_val, comment=comment
                        ))
        db.session.commit()
        flash(f'ATL ratings saved for {student.name} — {term}', 'success')
        return redirect(url_for('ib_atl_admin', student_id=sid, term=term))
    return render_template('ib/atl_admin.html',
        students=students, selected_student=selected_student,
        selected_term=selected_term, student_id=student_id,
        atl_skills=ATL_SKILLS, terms=TERMS,
        existing_ratings=existing_ratings,
        atl_descriptors=ATL_DESCRIPTORS)


# ── Teacher: Learner Profile Rating ───────────────────────────────────────────
@app.route('/ib/lp', methods=['GET','POST'])
@login_required('Resource_Manager')
def ib_lp_admin():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    selected_student = None
    selected_term = request.args.get('term', 'Term 1')
    student_id = request.args.get('student_id', type=int)
    teacher_ratings = {}
    student_ratings = {}
    if student_id:
        selected_student = db.session.get(User, student_id)
        t_ratings = LearnerProfileRating.query.filter_by(
            student_id=student_id, term=selected_term, rater_type='teacher'
        ).all()
        for r in t_ratings:
            teacher_ratings[r.attribute] = {'rating': r.rating, 'evidence': r.evidence or ''}
        s_ratings = LearnerProfileRating.query.filter_by(
            student_id=student_id, term=selected_term, rater_type='student'
        ).all()
        for r in s_ratings:
            student_ratings[r.attribute] = {'rating': r.rating, 'evidence': r.evidence or ''}
    if request.method == 'POST':
        sid  = int(request.form.get('student_id'))
        term = request.form.get('term')
        student = db.session.get(User, sid)
        for attr in LEARNER_PROFILE:
            rating_val = request.form.get(f'rating_{attr}', type=int)
            evidence   = request.form.get(f'evidence_{attr}', '').strip()
            if rating_val:
                existing = LearnerProfileRating.query.filter_by(
                    student_id=sid, term=term,
                    attribute=attr, rater_type='teacher'
                ).first()
                if existing:
                    existing.rating = rating_val
                    existing.evidence = evidence
                else:
                    db.session.add(LearnerProfileRating(
                        student_id=sid, rater_id=session['user_id'],
                        rater_type='teacher', term=term,
                        attribute=attr, rating=rating_val, evidence=evidence
                    ))
        db.session.commit()
        flash(f'Learner Profile saved for {student.name} — {term}', 'success')
        return redirect(url_for('ib_lp_admin', student_id=sid, term=term))
    return render_template('ib/lp_admin.html',
        students=students, selected_student=selected_student,
        selected_term=selected_term, student_id=student_id,
        learner_profile=LEARNER_PROFILE, lp_descriptions=LP_DESCRIPTIONS,
        lp_descriptors=LP_DESCRIPTORS, terms=TERMS,
        teacher_ratings=teacher_ratings, student_ratings=student_ratings)


# ── Student: Self-rate ATL ────────────────────────────────────────────────────
@app.route('/ib/student/atl', methods=['GET','POST'])
@login_required('student')
def ib_student_atl():
    student  = db.session.get(User, session['user_id'])
    selected_term = request.args.get('term', 'Term 1')
    my_ratings    = {}
    teacher_ratings = {}
    ratings = ATLRating.query.filter_by(student_id=student.id, term=selected_term).all()
    for r in ratings:
        key = f"{r.category}|{r.skill}"
        if r.rater_type == 'student':
            my_ratings[key] = {'rating': r.rating, 'comment': r.comment or ''}
        else:
            teacher_ratings[key] = {'rating': r.rating, 'comment': r.comment or ''}
    if request.method == 'POST':
        term = request.form.get('term')
        for cat, skills in ATL_SKILLS.items():
            for skill in skills:
                key = f"{cat}|{skill}"
                rating_val = request.form.get(f'rating_{key}', type=int)
                comment    = request.form.get(f'comment_{key}', '').strip()
                if rating_val:
                    existing = ATLRating.query.filter_by(
                        student_id=student.id, term=term,
                        category=cat, skill=skill, rater_type='student'
                    ).first()
                    if existing:
                        existing.rating = rating_val
                        existing.comment = comment
                    else:
                        db.session.add(ATLRating(
                            student_id=student.id, rater_id=student.id,
                            rater_type='student', term=term,
                            category=cat, skill=skill,
                            rating=rating_val, comment=comment
                        ))
        db.session.commit()
        flash('Your ATL self-assessment saved!', 'success')
        return redirect(url_for('ib_student_atl', term=term))
    grade = student.grade or 'Grade 3'
    descriptors = ATL_DESCRIPTORS.get(grade, ATL_DESCRIPTORS['Grade 3'])
    return render_template('ib/student_atl.html',
        student=student, selected_term=selected_term,
        atl_skills=ATL_SKILLS, terms=TERMS,
        my_ratings=my_ratings, teacher_ratings=teacher_ratings,
        descriptors=descriptors)


# ── Student: Self-rate Learner Profile ───────────────────────────────────────
@app.route('/ib/student/lp', methods=['GET','POST'])
@login_required('student')
def ib_student_lp():
    student      = db.session.get(User, session['user_id'])
    selected_term = request.args.get('term', 'Term 1')
    my_ratings    = {}
    teacher_ratings = {}
    ratings = LearnerProfileRating.query.filter_by(
        student_id=student.id, term=selected_term
    ).all()
    for r in ratings:
        if r.rater_type == 'student':
            my_ratings[r.attribute] = {'rating': r.rating, 'evidence': r.evidence or ''}
        else:
            teacher_ratings[r.attribute] = {'rating': r.rating, 'evidence': r.evidence or ''}
    # Reflection
    reflection = StudentReflection.query.filter_by(
        student_id=student.id, term=selected_term
    ).first()
    if request.method == 'POST':
        action = request.form.get('action')
        term   = request.form.get('term')
        if action == 'lp':
            for attr in LEARNER_PROFILE:
                rating_val = request.form.get(f'rating_{attr}', type=int)
                evidence   = request.form.get(f'evidence_{attr}', '').strip()
                if rating_val:
                    existing = LearnerProfileRating.query.filter_by(
                        student_id=student.id, term=term,
                        attribute=attr, rater_type='student'
                    ).first()
                    if existing:
                        existing.rating = rating_val
                        existing.evidence = evidence
                    else:
                        db.session.add(LearnerProfileRating(
                            student_id=student.id, rater_id=student.id,
                            rater_type='student', term=term,
                            attribute=attr, rating=rating_val, evidence=evidence
                        ))
            db.session.commit()
            flash('Learner Profile self-assessment saved!', 'success')
        elif action == 'reflection':
            ref_text = request.form.get('reflection','').strip()
            goals    = request.form.get('goals','').strip()
            if reflection:
                reflection.reflection = ref_text
                reflection.goals = goals
            else:
                db.session.add(StudentReflection(
                    student_id=student.id, term=term,
                    reflection=ref_text, goals=goals
                ))
            db.session.commit()
            flash('Reflection saved!', 'success')
        return redirect(url_for('ib_student_lp', term=term))
    grade = student.grade or 'Grade 3'
    lp_desc = LP_DESCRIPTORS.get(grade, LP_DESCRIPTORS['Grade 3'])
    return render_template('ib/student_lp.html',
        student=student, selected_term=selected_term,
        learner_profile=LEARNER_PROFILE, lp_descriptions=LP_DESCRIPTIONS,
        terms=TERMS, my_ratings=my_ratings, teacher_ratings=teacher_ratings,
        lp_desc=lp_desc, reflection=reflection)


# ── IB Overview / Dashboard ────────────────────────────────────────────────────
@app.route('/ib/overview')
@login_required('Resource_Manager')
def ib_overview():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    term     = request.args.get('term', 'Term 1')
    grade    = request.args.get('grade', '')
    # Build summary per student
    summary = []
    for s in students:
        if grade and s.grade != grade:
            continue
        t_lp = LearnerProfileRating.query.filter_by(
            student_id=s.id, term=term, rater_type='teacher'
        ).all()
        s_lp = LearnerProfileRating.query.filter_by(
            student_id=s.id, term=term, rater_type='student'
        ).all()
        t_atl = ATLRating.query.filter_by(
            student_id=s.id, term=term, rater_type='teacher'
        ).all()
        t_lp_avg  = round(sum(r.rating for r in t_lp)/len(t_lp), 1) if t_lp else None
        s_lp_avg  = round(sum(r.rating for r in s_lp)/len(s_lp), 1) if s_lp else None
        t_atl_avg = round(sum(r.rating for r in t_atl)/len(t_atl), 1) if t_atl else None
        summary.append({
            'student': s,
            't_lp_avg': t_lp_avg,
            's_lp_avg': s_lp_avg,
            't_atl_avg': t_atl_avg,
            'lp_done': len(t_lp),
            'atl_done': len(t_atl),
        })
    grades = ['Grade 3', 'Grade 4', 'Grade 5']
    return render_template('ib/overview.html',
        summary=summary, term=term, terms=TERMS,
        grades=grades, selected_grade=grade,
        learner_profile=LEARNER_PROFILE)


# ── IB HOLISTIC ROUTES ───────────────────────────────────────────────────────

# ── Admin: ATL Rating ──
@app.route('/admin/atl', methods=['GET','POST'])
@login_required('Resource_Manager')
def admin_atl():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    selected_student_id = request.args.get('student_id', type=int)
    selected_term = request.args.get('term', 'Term 1')
    selected_student = db.session.get(User, selected_student_id) if selected_student_id else None

    if request.method == 'POST':
        student_id = int(request.form.get('student_id'))
        term       = request.form.get('term')
        student    = db.session.get(User, student_id)
        for category, skills in ATL_SKILLS.items():
            for skill in skills:
                key = f"{category}|{skill}"
                rating = request.form.get(key)
                notes  = request.form.get(f"notes|{key}", '')
                if rating:
                    existing = ATLRating.query.filter_by(
                        student_id=student_id, term=term,
                        category=category, skill=skill
                    ).first()
                    if existing:
                        existing.rating = int(rating)
                        existing.notes  = notes
                        existing.teacher_id = session['user_id']
                    else:
                        db.session.add(ATLRating(
                            student_id=student_id, teacher_id=session['user_id'],
                            term=term, category=category, skill=skill,
                            rating=int(rating), notes=notes
                        ))
        db.session.commit()
        flash(f'ATL ratings saved for {student.name} — {term}', 'success')
        return redirect(url_for('admin_atl', student_id=student_id, term=term))

    # Load existing ratings
    existing_ratings = {}
    if selected_student:
        ratings = ATLRating.query.filter_by(
            student_id=selected_student_id, term=selected_term
        ).all()
        for r in ratings:
            existing_ratings[f"{r.category}|{r.skill}"] = {'rating': r.rating, 'notes': r.notes or ''}

    return render_template('admin/atl.html',
        students=students, selected_student=selected_student,
        selected_term=selected_term, terms=TERMS,
        atl_skills=ATL_SKILLS, existing_ratings=existing_ratings,
        descriptors=ATL_DESCRIPTORS.get(selected_student.grade if selected_student else 'Grade 3', ATL_DESCRIPTORS['Grade 3'])
    )


# ── Admin: Learner Profile Rating ──
@app.route('/admin/learner-profile', methods=['GET','POST'])
@login_required('Resource_Manager')
def admin_learner_profile():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    selected_student_id = request.args.get('student_id', type=int)
    selected_term = request.args.get('term', 'Term 1')
    selected_student = db.session.get(User, selected_student_id) if selected_student_id else None

    if request.method == 'POST':
        student_id = int(request.form.get('student_id'))
        term       = request.form.get('term')
        for attr, _, _ in LEARNER_PROFILE:
            rating   = request.form.get(f'rating|{attr}')
            evidence = request.form.get(f'evidence|{attr}', '')
            if rating:
                existing = LearnerProfileRating.query.filter_by(
                    student_id=student_id, term=term,
                    attribute=attr, rater_type='teacher'
                ).first()
                if existing:
                    existing.rating   = int(rating)
                    existing.evidence = evidence
                else:
                    db.session.add(LearnerProfileRating(
                        student_id=student_id, rater_id=session['user_id'],
                        rater_type='teacher', term=term,
                        attribute=attr, rating=int(rating), evidence=evidence
                    ))
        db.session.commit()
        flash('Learner Profile ratings saved!', 'success')
        return redirect(url_for('admin_learner_profile', student_id=student_id, term=term))

    teacher_ratings = {}
    student_ratings = {}
    if selected_student:
        for r in LearnerProfileRating.query.filter_by(student_id=selected_student_id, term=selected_term).all():
            if r.rater_type == 'teacher':
                teacher_ratings[r.attribute] = {'rating': r.rating, 'evidence': r.evidence or ''}
            else:
                student_ratings[r.attribute] = {'rating': r.rating, 'evidence': r.evidence or ''}

    return render_template('admin/learner_profile.html',
        students=students, selected_student=selected_student,
        selected_term=selected_term, terms=TERMS,
        learner_profile=LEARNER_PROFILE,
        teacher_ratings=teacher_ratings, student_ratings=student_ratings,
    )


# ── Admin: IB Overview ──
@app.route('/admin/ib-overview')
@login_required('Resource_Manager')
def admin_ib_overview():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    term = request.args.get('term', 'Term 1')
    grade = request.args.get('grade', '')
    overview = []
    for s in students:
        if grade and s.grade != grade:
            continue
        atl_avg = 0
        atl_count = 0
        for r in ATLRating.query.filter_by(student_id=s.id, term=term).all():
            atl_avg += r.rating; atl_count += 1
        atl_avg = round(atl_avg/atl_count, 1) if atl_count else 0
        lp_avg = 0; lp_count = 0
        for r in LearnerProfileRating.query.filter_by(student_id=s.id, term=term, rater_type='teacher').all():
            lp_avg += r.rating; lp_count += 1
        lp_avg = round(lp_avg/lp_count, 1) if lp_count else 0
        overview.append({
            'student': s, 'atl_avg': atl_avg,
            'lp_avg': lp_avg, 'atl_done': atl_count > 0, 'lp_done': lp_count > 0
        })
    return render_template('admin/ib_overview.html',
        overview=overview, term=term, terms=TERMS,
        grades=['Grade 3','Grade 4','Grade 5'], selected_grade=grade,
        learner_profile=LEARNER_PROFILE
    )


# ── Student: Self-rate Learner Profile ──
@app.route('/student/learner-profile', methods=['GET','POST'])
@login_required('student')
def student_learner_profile():
    student = db.session.get(User, session['user_id'])
    selected_term = request.args.get('term', 'Term 1')

    if request.method == 'POST':
        term = request.form.get('term')
        for attr, _, _ in LEARNER_PROFILE:
            rating    = request.form.get(f'rating|{attr}')
            evidence  = request.form.get(f'evidence|{attr}', '')
            if rating:
                existing = LearnerProfileRating.query.filter_by(
                    student_id=student.id, term=term,
                    attribute=attr, rater_type='student'
                ).first()
                if existing:
                    existing.rating   = int(rating)
                    existing.evidence = evidence
                else:
                    db.session.add(LearnerProfileRating(
                        student_id=student.id, rater_id=student.id,
                        rater_type='student', term=term,
                        attribute=attr, rating=int(rating), evidence=evidence
                    ))
        # Save reflection
        reflection_text = request.form.get('reflection', '')
        goal_text       = request.form.get('goal', '')
        if reflection_text:
            existing_r = StudentReflection.query.filter_by(
                student_id=student.id, term=term
            ).first()
            if existing_r:
                existing_r.reflection = reflection_text
                existing_r.goal       = goal_text
            else:
                db.session.add(StudentReflection(
                    student_id=student.id, term=term,
                    reflection=reflection_text, goal=goal_text
                ))
        db.session.commit()
        flash('Your self-assessment saved!', 'success')
        return redirect(url_for('student_learner_profile', term=term))

    # Load ratings
    my_ratings      = {}
    teacher_ratings = {}
    for r in LearnerProfileRating.query.filter_by(student_id=student.id, term=selected_term).all():
        if r.rater_type == 'student':
            my_ratings[r.attribute]      = {'rating': r.rating, 'evidence': r.evidence or ''}
        else:
            teacher_ratings[r.attribute] = {'rating': r.rating, 'evidence': r.evidence or ''}

    my_atl = ATLRating.query.filter_by(student_id=student.id, term=selected_term).all()
    reflection = StudentReflection.query.filter_by(
        student_id=student.id, term=selected_term
    ).first()

    return render_template('student/learner_profile.html',
        student=student, selected_term=selected_term, terms=TERMS,
        learner_profile=LEARNER_PROFILE, my_ratings=my_ratings,
        teacher_ratings=teacher_ratings, my_atl=my_atl,
        atl_skills=ATL_SKILLS, reflection=reflection,
        descriptors=ATL_DESCRIPTORS.get(student.grade, ATL_DESCRIPTORS['Grade 3'])
    )


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


# ── IB DEVELOPMENT ROUTES ────────────────────────────────────────────────────

@app.route('/admin/ib')
@login_required('Resource_Manager')
def ib_dashboard():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    total_atl = ATLRating.query.count()
    total_lp  = LPRating.query.count()
    return render_template('ib/dashboard.html',
        students=students, total_atl=total_atl, total_lp=total_lp,
        terms=TERMS, atl_skills=list(ATL_SKILLS.keys()),
        lp_attributes=IB_LEARNER_PROFILE)


@app.route('/admin/ib/atl/<int:student_id>', methods=['GET','POST'])
@login_required('Resource_Manager')
def ib_atl_teacher(student_id):
    student = db.session.get(User, student_id)
    if not student: return redirect(url_for('ib_dashboard'))
    grade = student.grade or 'Grade 3'
    descriptors = ATL_SKILLS

    if request.method == 'POST':
        term = request.form.get('term')
        for skill, grade_descs in descriptors.items():
            descs = grade_descs.get(grade, [])
            for i, desc in enumerate(descs):
                key = f"{skill}_{i}"
                rating = request.form.get(key)
                comment = request.form.get(f"comment_{skill}_{i}", '')
                if rating:
                    # Update or create
                    existing = ATLRating.query.filter_by(
                        student_id=student_id, term=term,
                        skill=skill, descriptor=desc
                    ).first()
                    if existing:
                        existing.rating = int(rating)
                        existing.comment = comment
                    else:
                        db.session.add(ATLRating(
                            student_id=student_id,
                            teacher_id=session['user_id'],
                            term=term, skill=skill,
                            descriptor=desc, rating=int(rating),
                            comment=comment
                        ))
        db.session.commit()
        flash(f'ATL ratings saved for {student.name} — {term}', 'success')

    # Load existing ratings
    ratings = {}
    for r in ATLRating.query.filter_by(student_id=student_id).all():
        ratings[(r.term, r.skill, r.descriptor)] = {'rating': r.rating, 'comment': r.comment or ''}

    return render_template('ib/atl_teacher.html',
        student=student, grade=grade, terms=TERMS,
        atl_skills=descriptors, ratings=ratings,
        rating_labels=RATING_LABELS)


@app.route('/admin/ib/lp/<int:student_id>', methods=['GET','POST'])
@login_required('Resource_Manager')
def ib_lp_teacher(student_id):
    student = db.session.get(User, student_id)
    if not student: return redirect(url_for('ib_dashboard'))

    if request.method == 'POST':
        term = request.form.get('term')
        for attr, icon, desc in IB_LEARNER_PROFILE:
            rating   = request.form.get(f'rating_{attr}')
            evidence = request.form.get(f'evidence_{attr}', '')
            if rating:
                existing = LPRating.query.filter_by(
                    student_id=student_id, term=term,
                    attribute=attr, rater_type='teacher'
                ).first()
                if existing:
                    existing.rating = int(rating)
                    existing.evidence = evidence
                else:
                    db.session.add(LPRating(
                        student_id=student_id,
                        rater_id=session['user_id'],
                        rater_type='teacher', term=term,
                        attribute=attr, rating=int(rating),
                        evidence=evidence
                    ))
        db.session.commit()
        flash(f'Learner Profile saved for {student.name} — {term}', 'success')

    teacher_ratings = {}
    student_ratings = {}
    for r in LPRating.query.filter_by(student_id=student_id).all():
        if r.rater_type == 'teacher':
            teacher_ratings[(r.term, r.attribute)] = {'rating': r.rating, 'evidence': r.evidence or ''}
        else:
            student_ratings[(r.term, r.attribute)] = {'rating': r.rating, 'evidence': r.evidence or ''}

    return render_template('ib/lp_teacher.html',
        student=student, terms=TERMS,
        lp_attributes=IB_LEARNER_PROFILE,
        teacher_ratings=teacher_ratings,
        student_ratings=student_ratings,
        rating_labels=RATING_LABELS)


@app.route('/student/ib')
@login_required('student')
def student_ib():
    student = db.session.get(User, session['user_id'])
    atl_ratings = ATLRating.query.filter_by(student_id=student.id).all()
    lp_ratings  = LPRating.query.filter_by(student_id=student.id).all()
    reflections = StudentReflection.query.filter_by(student_id=student.id).order_by(StudentReflection.term).all()

    teacher_lp = {}
    student_lp = {}
    for r in lp_ratings:
        if r.rater_type == 'teacher':
            teacher_lp[(r.term, r.attribute)] = {'rating': r.rating, 'evidence': r.evidence or ''}
        else:
            student_lp[(r.term, r.attribute)]  = {'rating': r.rating, 'evidence': r.evidence or ''}

    atl_by_term = {}
    for r in atl_ratings:
        atl_by_term.setdefault(r.term, {}).setdefault(r.skill, []).append(r)

    return render_template('ib/student_ib.html',
        student=student, terms=TERMS,
        atl_by_term=atl_by_term,
        lp_attributes=IB_LEARNER_PROFILE,
        teacher_lp=teacher_lp, student_lp=student_lp,
        reflections=reflections, rating_labels=RATING_LABELS,
        atl_skills=list(ATL_SKILLS.keys()))


@app.route('/student/ib/self-rate', methods=['POST'])
@login_required('student')
def student_lp_selfrate():
    student_id = session['user_id']
    term = request.form.get('term')
    for attr, icon, desc in IB_LEARNER_PROFILE:
        rating   = request.form.get(f'rating_{attr}')
        evidence = request.form.get(f'evidence_{attr}', '')
        if rating:
            existing = LPRating.query.filter_by(
                student_id=student_id, term=term,
                attribute=attr, rater_type='student'
            ).first()
            if existing:
                existing.rating = int(rating)
                existing.evidence = evidence
            else:
                db.session.add(LPRating(
                    student_id=student_id, rater_id=student_id,
                    rater_type='student', term=term,
                    attribute=attr, rating=int(rating), evidence=evidence
                ))
    db.session.commit()
    flash('Your self-rating has been saved!', 'success')
    return redirect(url_for('student_ib'))


@app.route('/student/ib/reflect', methods=['POST'])
@login_required('student')
def student_reflect():
    student_id = session['user_id']
    term       = request.form.get('term')
    reflection = request.form.get('reflection', '').strip()
    goal       = request.form.get('goal', '').strip()
    if reflection:
        existing = StudentReflection.query.filter_by(
            student_id=student_id, term=term
        ).first()
        if existing:
            existing.reflection = reflection
            existing.goal = goal
        else:
            db.session.add(StudentReflection(
                student_id=student_id, term=term,
                reflection=reflection, goal=goal
            ))
        db.session.commit()
        flash('Reflection saved!', 'success')
    return redirect(url_for('student_ib'))


@app.route('/admin/ib/report/<int:student_id>')
@login_required('Resource_Manager')
def ib_student_report(student_id):
    student     = db.session.get(User, student_id)
    atl_ratings = ATLRating.query.filter_by(student_id=student_id).all()
    lp_ratings  = LPRating.query.filter_by(student_id=student_id).all()
    reflections = StudentReflection.query.filter_by(student_id=student_id).all()
    test_results= TestResult.query.filter_by(student_id=student_id).all()

    teacher_lp = {}
    student_lp = {}
    for r in lp_ratings:
        if r.rater_type == 'teacher':
            teacher_lp[(r.term, r.attribute)] = r.rating
        else:
            student_lp[(r.term, r.attribute)]  = r.rating

    atl_summary = {}
    for r in atl_ratings:
        atl_summary.setdefault(r.term, {}).setdefault(r.skill, []).append(r.rating)
    atl_avgs = {
        term: {skill: round(sum(vals)/len(vals),1) for skill, vals in skills.items()}
        for term, skills in atl_summary.items()
    }

    return render_template('ib/student_report.html',
        student=student, terms=TERMS,
        lp_attributes=IB_LEARNER_PROFILE,
        teacher_lp=teacher_lp, student_lp=student_lp,
        atl_avgs=atl_avgs, reflections={r.term: r for r in reflections},
        test_results=test_results, rating_labels=RATING_LABELS,
        atl_skills=list(ATL_SKILLS.keys()))


# ── IB DEVELOPMENT ROUTES ────────────────────────────────────────────────────

@app.route('/ib/dashboard')
@login_required('Resource_Manager')
def ib_dashboard():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    total_atl = ATLRating.query.count()
    total_lp  = LPRating.query.count()
    return render_template('ib/dashboard.html',
        students=students, total_atl=total_atl, total_lp=total_lp,
        terms=TERMS, atl_categories=ATL_CATEGORIES,
        learner_profile=LEARNER_PROFILE)


@app.route('/ib/student/<int:student_id>', methods=['GET','POST'])
@login_required('Resource_Manager')
def ib_student_detail(student_id):
    student  = db.session.get(User, student_id)
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('ib_dashboard'))
    term = request.args.get('term', 'Term 1')

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_atl':
            for cat_key, cat in ATL_CATEGORIES.items():
                for skill in cat['skills']:
                    field = f"{cat_key}_{skill.replace(' ','_').replace('&','').replace('/','_')}"
                    rating_val = request.form.get(field)
                    comment    = request.form.get(f"{field}_comment", '')
                    if rating_val:
                        existing = ATLRating.query.filter_by(
                            student_id=student_id,
                            term=term, category=cat_key, skill=skill
                        ).first()
                        if existing:
                            existing.rating  = int(rating_val)
                            existing.comment = comment
                            existing.teacher_id = session['user_id']
                        else:
                            db.session.add(ATLRating(
                                student_id=student_id,
                                teacher_id=session['user_id'],
                                term=term, category=cat_key, skill=skill,
                                rating=int(rating_val), comment=comment
                            ))
            db.session.commit()
            flash('ATL ratings saved successfully!', 'success')

        elif action == 'save_lp':
            for attr, label, desc in LEARNER_PROFILE:
                rating_val = request.form.get(f"lp_{attr}")
                evidence   = request.form.get(f"lp_{attr}_evidence", '')
                if rating_val:
                    existing = LPRating.query.filter_by(
                        student_id=student_id, term=term,
                        attribute=attr, rater_type='teacher'
                    ).first()
                    if existing:
                        existing.rating   = int(rating_val)
                        existing.evidence = evidence
                        existing.rater_id = session['user_id']
                    else:
                        db.session.add(LPRating(
                            student_id=student_id,
                            rater_id=session['user_id'],
                            rater_type='teacher',
                            term=term, attribute=attr,
                            rating=int(rating_val), evidence=evidence
                        ))
            db.session.commit()
            flash('Learner Profile ratings saved!', 'success')

        return redirect(url_for('ib_student_detail', student_id=student_id, term=term))

    # Fetch existing ratings
    atl_ratings = {}
    for r in ATLRating.query.filter_by(student_id=student_id, term=term).all():
        atl_ratings[(r.category, r.skill)] = r

    lp_teacher = {}
    for r in LPRating.query.filter_by(student_id=student_id, term=term, rater_type='teacher').all():
        lp_teacher[r.attribute] = r

    lp_student = {}
    for r in LPRating.query.filter_by(student_id=student_id, term=term, rater_type='student').all():
        lp_student[r.attribute] = r

    reflection = StudentReflection.query.filter_by(
        student_id=student_id, term=term
    ).first()

    return render_template('ib/student_detail.html',
        student=student, term=term, terms=TERMS,
        atl_categories=ATL_CATEGORIES, atl_ratings=atl_ratings,
        learner_profile=LEARNER_PROFILE, lp_teacher=lp_teacher,
        lp_student=lp_student, reflection=reflection,
        rating_labels=RATING_LABELS, rating_colors=RATING_COLORS,
        rating_text=RATING_TEXT)


@app.route('/ib/class-overview')
@login_required('Resource_Manager')
def ib_class_overview():
    term  = request.args.get('term', 'Term 1')
    grade = request.args.get('grade', '')
    students = User.query.filter_by(role='student')
    if grade:
        students = students.filter_by(grade=grade)
    students = students.order_by(User.grade, User.name).all()

    # Build overview data
    overview = []
    for s in students:
        atl_data = {}
        for cat_key in ATL_CATEGORIES:
            ratings = ATLRating.query.filter_by(
                student_id=s.id, term=term, category=cat_key
            ).all()
            avg = round(sum(r.rating for r in ratings)/len(ratings), 1) if ratings else 0
            atl_data[cat_key] = avg

        lp_data = {}
        for attr, label, desc in LEARNER_PROFILE:
            tr = LPRating.query.filter_by(
                student_id=s.id, term=term,
                attribute=attr, rater_type='teacher'
            ).first()
            lp_data[attr] = tr.rating if tr else 0

        overall_atl = round(sum(atl_data.values())/len(atl_data), 1) if atl_data else 0
        overview.append({
            'student': s, 'atl': atl_data,
            'lp': lp_data, 'overall_atl': overall_atl
        })

    return render_template('ib/class_overview.html',
        overview=overview, term=term, terms=TERMS,
        grade=grade, grades=['Grade 3','Grade 4','Grade 5'],
        atl_categories=ATL_CATEGORIES,
        learner_profile=LEARNER_PROFILE,
        rating_labels=RATING_LABELS,
        rating_colors=RATING_COLORS,
        rating_text=RATING_TEXT)


# ── STUDENT IB ROUTES ──────────────────────────────────────────────────────

@app.route('/student/ib')
@login_required('student')
def student_ib_dashboard():
    student = db.session.get(User, session['user_id'])
    term    = request.args.get('term', 'Term 1')

    lp_self    = {r.attribute: r for r in LPRating.query.filter_by(
        student_id=student.id, term=term, rater_type='student').all()}
    lp_teacher = {r.attribute: r for r in LPRating.query.filter_by(
        student_id=student.id, term=term, rater_type='teacher').all()}
    atl_ratings = {(r.category, r.skill): r for r in ATLRating.query.filter_by(
        student_id=student.id, term=term).all()}
    reflection = StudentReflection.query.filter_by(
        student_id=student.id, term=term).first()

    return render_template('student/ib_dashboard.html',
        student=student, term=term, terms=TERMS,
        learner_profile=LEARNER_PROFILE,
        atl_categories=ATL_CATEGORIES,
        lp_self=lp_self, lp_teacher=lp_teacher,
        atl_ratings=atl_ratings, reflection=reflection,
        rating_labels=RATING_LABELS,
        rating_colors=RATING_COLORS,
        rating_text=RATING_TEXT)


@app.route('/student/ib/self-rate', methods=['POST'])
@login_required('student')
def student_self_rate():
    student = db.session.get(User, session['user_id'])
    term    = request.form.get('term', 'Term 1')

    for attr, label, desc in LEARNER_PROFILE:
        rating_val = request.form.get(f"lp_{attr}")
        evidence   = request.form.get(f"lp_{attr}_evidence", '')
        if rating_val:
            existing = LPRating.query.filter_by(
                student_id=student.id, term=term,
                attribute=attr, rater_type='student'
            ).first()
            if existing:
                existing.rating   = int(rating_val)
                existing.evidence = evidence
            else:
                db.session.add(LPRating(
                    student_id=student.id,
                    rater_id=student.id,
                    rater_type='student',
                    term=term, attribute=attr,
                    rating=int(rating_val), evidence=evidence
                ))

    # Save reflection
    reflection_text = request.form.get('reflection', '')
    goal_text       = request.form.get('goal', '')
    if reflection_text:
        existing_ref = StudentReflection.query.filter_by(
            student_id=student.id, term=term
        ).first()
        if existing_ref:
            existing_ref.reflection = reflection_text
            existing_ref.goal       = goal_text
        else:
            db.session.add(StudentReflection(
                student_id=student.id, term=term,
                reflection=reflection_text, goal=goal_text
            ))

    db.session.commit()
    flash('Your self-assessment saved successfully! ✅', 'success')
    return redirect(url_for('student_ib_dashboard', term=term))


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
    filter_grade   = request.args.get('grade', '')
    filter_section = request.args.get('section', '')
    filter_subject = request.args.get('subject', '')
    data = build_analytics(
        filter_grade   = filter_grade   or None,
        filter_section = filter_section or None,
        filter_subject = filter_subject or None,
    )
    data['filter_grade']   = filter_grade
    data['filter_section'] = filter_section
    data['filter_subject'] = filter_subject
    data['sections']       = ['A','B','C','D']
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

# ── IB HOLISTIC ROUTES ────────────────────────────────────────────────────────

@app.route('/ib')
@login_required('Resource_Manager')
def ib_dashboard():
    students = User.query.filter_by(role='student').all()
    total_atl = ATLRating.query.count()
    total_lp  = LearnerProfileRating.query.count()
    # Average LP ratings per attribute
    lp_avgs = {}
    for attr, _ in LEARNER_PROFILE:
        ratings = LearnerProfileRating.query.filter_by(attribute=attr).all()
        lp_avgs[attr] = round(sum(r.rating for r in ratings)/len(ratings),1) if ratings else 0
    return render_template('ib/dashboard.html',
        students=students, total_atl=total_atl, total_lp=total_lp,
        lp_avgs=lp_avgs, learner_profile=LEARNER_PROFILE,
        rating_scale=RATING_SCALE, rating_colors=RATING_COLORS,
        atl_skills=ATL_SKILLS, terms=TERMS)


@app.route('/ib/atl', methods=['GET','POST'])
@login_required('Resource_Manager')
def ib_atl():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    if request.method == 'POST':
        student_id = int(request.form.get('student_id'))
        term       = request.form.get('term')
        skill      = request.form.get('skill')
        rater_type = 'teacher'
        student    = db.session.get(User, student_id)
        grade      = student.grade if student else 'Grade 3'
        descriptors = ATL_SKILLS.get(skill, {}).get(grade, [])
        saved = 0
        for i, desc in enumerate(descriptors):
            rating_val = request.form.get(f'rating_{i}')
            if rating_val:
                existing = ATLRating.query.filter_by(
                    student_id=student_id, term=term,
                    skill=skill, descriptor=desc, rater_type=rater_type
                ).first()
                if existing:
                    existing.rating = int(rating_val)
                else:
                    db.session.add(ATLRating(
                        student_id=student_id, teacher_id=session['user_id'],
                        term=term, skill=skill, descriptor=desc,
                        rating=int(rating_val), rater_type=rater_type
                    ))
                saved += 1
        db.session.commit()
        flash(f'ATL ratings saved for {student.name} — {skill} ({term})', 'success')
        return redirect(url_for('ib_atl'))

    selected_student = request.args.get('student_id', type=int)
    selected_term    = request.args.get('term', 'Term 1')

    # Get existing ratings for selected student
    existing_ratings = {}
    if selected_student:
        ratings = ATLRating.query.filter_by(
            student_id=selected_student, term=selected_term, rater_type='teacher'
        ).all()
        for r in ratings:
            existing_ratings[(r.skill, r.descriptor)] = r.rating

    return render_template('ib/atl.html',
        students=students, terms=TERMS,
        atl_skills=ATL_SKILLS, rating_scale=RATING_SCALE,
        selected_student=selected_student, selected_term=selected_term,
        existing_ratings=existing_ratings)


@app.route('/ib/learner-profile', methods=['GET','POST'])
@login_required('Resource_Manager')
def ib_learner_profile():
    students = User.query.filter_by(role='student').order_by(User.grade, User.name).all()
    if request.method == 'POST':
        student_id = int(request.form.get('student_id'))
        term       = request.form.get('term')
        student    = db.session.get(User, student_id)
        for attr, _ in LEARNER_PROFILE:
            t_rating = request.form.get(f'teacher_{attr}')
            evidence = request.form.get(f'evidence_{attr}', '')
            if t_rating:
                existing = LearnerProfileRating.query.filter_by(
                    student_id=student_id, term=term,
                    attribute=attr, rater_type='teacher'
                ).first()
                if existing:
                    existing.rating = int(t_rating)
                    existing.evidence = evidence
                else:
                    db.session.add(LearnerProfileRating(
                        student_id=student_id, teacher_id=session['user_id'],
                        term=term, attribute=attr,
                        rating=int(t_rating), rater_type='teacher', evidence=evidence
                    ))
        db.session.commit()
        flash(f'Learner Profile saved for {student.name} ({term})', 'success')
        return redirect(url_for('ib_learner_profile'))

    selected_student = request.args.get('student_id', type=int)
    selected_term    = request.args.get('term', 'Term 1')
    existing_ratings = {}
    existing_evidence = {}
    if selected_student:
        ratings = LearnerProfileRating.query.filter_by(
            student_id=selected_student, term=selected_term, rater_type='teacher'
        ).all()
        for r in ratings:
            existing_ratings[r.attribute]  = r.rating
            existing_evidence[r.attribute] = r.evidence or ''

    return render_template('ib/learner_profile.html',
        students=students, terms=TERMS,
        learner_profile=LEARNER_PROFILE, rating_scale=RATING_SCALE,
        rating_colors=RATING_COLORS,
        selected_student=selected_student, selected_term=selected_term,
        existing_ratings=existing_ratings, existing_evidence=existing_evidence)


@app.route('/ib/report/<int:student_id>')
@login_required('Resource_Manager')
def ib_student_report(student_id):
    student = db.session.get(User, student_id)
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('ib_dashboard'))
    report = {}
    for term in TERMS:
        atl_data = {}
        for skill in ATL_SKILLS:
            ratings = ATLRating.query.filter_by(
                student_id=student_id, term=term, skill=skill, rater_type='teacher'
            ).all()
            if ratings:
                atl_data[skill] = {
                    'avg': round(sum(r.rating for r in ratings)/len(ratings), 1),
                    'descriptors': [(r.descriptor, r.rating) for r in ratings]
                }
        lp_data = {}
        for attr, desc in LEARNER_PROFILE:
            t_r = LearnerProfileRating.query.filter_by(
                student_id=student_id, term=term, attribute=attr, rater_type='teacher'
            ).first()
            s_r = LearnerProfileRating.query.filter_by(
                student_id=student_id, term=term, attribute=attr, rater_type='student'
            ).first()
            if t_r or s_r:
                lp_data[attr] = {
                    'teacher': t_r.rating if t_r else None,
                    'student': s_r.rating if s_r else None,
                    'evidence': t_r.evidence if t_r else '',
                }
        report[term] = {'atl': atl_data, 'lp': lp_data}

    test_results = TestResult.query.filter_by(student_id=student_id).all()
    return render_template('ib/student_report.html',
        student=student, report=report, terms=TERMS,
        learner_profile=LEARNER_PROFILE, atl_skills=list(ATL_SKILLS.keys()),
        rating_scale=RATING_SCALE, rating_colors=RATING_COLORS,
        test_results=test_results)


# ── STUDENT IB SELF-RATING ─────────────────────────────────────────────────────

@app.route('/student/ib', methods=['GET','POST'])
@login_required('student')
def student_ib():
    student  = db.session.get(User, session['user_id'])
    selected_term = request.args.get('term', 'Term 1')

    if request.method == 'POST':
        term = request.form.get('term')
        for attr, _ in LEARNER_PROFILE:
            s_rating    = request.form.get(f'self_{attr}')
            reflection  = request.form.get(f'reflection_{attr}', '')
            if s_rating:
                existing = LearnerProfileRating.query.filter_by(
                    student_id=student.id, term=term,
                    attribute=attr, rater_type='student'
                ).first()
                if existing:
                    existing.rating = int(s_rating)
                else:
                    db.session.add(LearnerProfileRating(
                        student_id=student.id, term=term,
                        attribute=attr, rating=int(s_rating), rater_type='student'
                    ))
            if reflection:
                existing_r = StudentReflection.query.filter_by(
                    student_id=student.id, term=term, attribute=attr
                ).first()
                if existing_r:
                    existing_r.reflection = reflection
                else:
                    db.session.add(StudentReflection(
                        student_id=student.id, term=term,
                        attribute=attr, reflection=reflection
                    ))
        db.session.commit()
        flash('Your self-assessment has been saved!', 'success')
        return redirect(url_for('student_ib', term=term))

    # Load existing self-ratings and reflections
    self_ratings = {}
    reflections  = {}
    ratings = LearnerProfileRating.query.filter_by(
        student_id=student.id, term=selected_term, rater_type='student'
    ).all()
    for r in ratings:
        self_ratings[r.attribute] = r.rating

    teacher_ratings = {}
    t_ratings = LearnerProfileRating.query.filter_by(
        student_id=student.id, term=selected_term, rater_type='teacher'
    ).all()
    for r in t_ratings:
        teacher_ratings[r.attribute] = r.rating

    refs = StudentReflection.query.filter_by(
        student_id=student.id, term=selected_term
    ).all()
    for r in refs:
        reflections[r.attribute] = r.reflection

    # ATL ratings from teacher
    atl_ratings = {}
    atl = ATLRating.query.filter_by(
        student_id=student.id, term=selected_term, rater_type='teacher'
    ).all()
    for r in atl:
        atl_ratings.setdefault(r.skill, []).append({'desc': r.descriptor, 'rating': r.rating})

    return render_template('student/ib.html',
        student=student, terms=TERMS, selected_term=selected_term,
        learner_profile=LEARNER_PROFILE, rating_scale=RATING_SCALE,
        rating_colors=RATING_COLORS,
        self_ratings=self_ratings, teacher_ratings=teacher_ratings,
        reflections=reflections, atl_ratings=atl_ratings)


# ── MAIN ──────────────────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()
    seed_db()

if __name__ == '__main__':
    print("\n🎓 Eastern Public School — IBT Portal")
    print("   Admin: Organizer / bk*123\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
