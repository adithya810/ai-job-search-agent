import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent

# Persistent browser profile directory to retain cookies and logged-in Google / portal sessions
BROWSER_PROFILE_DIR = BASE_DIR / ".chrome_profile"
BROWSER_CHANNEL = "chrome"

# Exa & Firecrawl API Keys loaded from environment variables / local .env (never hardcoded)
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_API_URL = os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev")

# Credentials loaded from environment variables / local .env (never hardcoded)
LOGIN_EMAIL = os.environ.get("JOB_AGENT_EMAIL", "adithyakrishna810@gmail.com")
GMAIL_LOGIN_EMAIL = LOGIN_EMAIL
LOGIN_PASSWORD = os.environ.get("JOB_AGENT_PASSWORD", "")

# Input & Output paths in the project folder
COMPANY_CHECK_SHEET = BASE_DIR / "Company name.xlsx"
APPLIED_COMPANIES_EXCEL = BASE_DIR / "Applied_Companies_Tracker.xlsx"
JOB_DISCOVERY_LOG = BASE_DIR / "Job_Search_Log.json"
MCP_DISCOVERED_JOBS_JSON = BASE_DIR / "mcp_discovered_jobs.json"
AGENT_MEMORY_STATE_PATH = BASE_DIR / "agent_memory_state.json"
APPLIED_JOBS_HISTORY_PATH = BASE_DIR / "applied_jobs_history.json"

# Resume files in project folder
RESUME_PDF_PATH = BASE_DIR / "Adithya_Krishna_Resume.pdf"
RESUME_DOCX_PATH = BASE_DIR / "Adithya_Krishna_Resume.docx"
MIS_RESUME_DOCX_PATH = BASE_DIR / "Adithya_Krishna_MIS_Executive_Resume.docx"
DA_RESUME_DOCX_PATH = BASE_DIR / "Adithya_Krishna_Data_Analyst_Resume.docx"
AIML_RESUME_DOCX_PATH = BASE_DIR / "Adithya_Krishna_AIML_Engineer_Resume.docx"
COVER_LETTER_PATH = BASE_DIR / "Adithya_Cover_Letter.docx"

# Matching & Filtering Thresholds
MATCH_THRESHOLD_PERCENT = 80.0
MAX_POSTED_AGE_HOURS = 48
STRICT_48_HOURS_FILTER = True
MAX_JOB_AGE_HOURS = 48
MAX_JOB_EXPERIENCE_YEARS = 5.0
STRICT_BELOW_4_YEARS_FILTER = True

# Candidate Profile & Resume Skills (Updated with Adithya Krishna's Full Resume)
CANDIDATE_PROFILE = {
    "full_name": "Adithya Krishna",
    "first_name": "Adithya",
    "last_name": "Krishna",
    "email": LOGIN_EMAIL,
    "phone": "9177059799",
    "phone_with_country": "+919177059799",
    "city": "Hyderabad",
    "state": "Telangana",
    "pincode": "500047",
    "country": "India",
    "linkedin_url": "https://www.linkedin.com/in/adithya-krishna-6aa058162",
    "total_experience_years": 4.5,
    "relevant_experience_years": 4.5,
    "current_company": "Deloitte",
    "current_designation": "Data Analyst / Insights Analyst",
    "target_designation": "AI/ML Engineer | Data Analyst | MIS Executive | Python | Power BI | SQL | ETL",
    "notice_period_days": 0,
    "notice_period_label": "Immediate / 0-15 Days",
    "current_ctc_lpa": 8.0,
    "expected_ctc_lpa": 12.0,
    "citizenship": "Indian",
    "nationality": "Indian",
    "work_authorization": "Yes",
    "visa_status": "Indian Citizen / Valid Visa & Work Authorization",
    "screening_defaults": {
        "total_experience_years": "4.5",
        "relevant_experience_years": "4.0",
        "notice_period_days": "15",
        "current_ctc_lpa": "8",
        "expected_ctc_lpa": "12",
        "authorized_in_india": "Yes",
        "legally_authorized": "Yes",
        "work_authorization": "Yes",
        "have_valid_visa": "Yes",
        "citizenship": "Indian",
        "nationality": "Indian",
        "country_of_citizenship": "India",
        "requires_visa_sponsorship": "No",
        "willing_to_relocate": "Yes",
    },
    "preferred_locations": [
        "Hyderabad",
        "Bengaluru",
        "Bangalore",
        "Gurugram",
        "Gurgaon",
        "Chennai",
    ],
    "target_roles": [
        "Data Analyst",
        "MIS Executive",
        "AI/ML Engineer",
        "Machine Learning Engineer",
        "Data Scientist",
        "Insights Analyst",
        "Power BI Developer",
        "Power BI Analyst",
        "MIS Analyst",
        "Reporting Analyst",
        "Operations Analyst",
        "Claims Reporting Analyst",
        "Data Engineer",
        "ETL Developer",
        "Business Data Analyst",
        "Junior Data Analyst",
        "Associate Data Analyst",
    ],
    "skill_categories": {
        "ML Libraries & Packages": [
            "Scikit-learn", "NumPy", "Pandas", "Matplotlib", "Seaborn", "TensorFlow", "Machine Learning", "Regression", "Classification"
        ],
        "Deep Learning & NLP": [
            "PyTorch", "spaCy", "Keras", "Deep Learning", "NLP", "LSTM", "CNN", "Self-Attention", "Transformers"
        ],
        "Generative AI & Agentic Workflows": [
            "Generative AI", "GenAI", "LLMs", "Prompt Engineering", "Agentic Workflows", "Agentic AI", "Task Automation", "MCP Connectors"
        ],
        "Programming & Databases": [
            "Python", "Pandas", "NumPy", "Openpyxl", "SQL", "SQL Server", "SSMS", "SSIS", "MySQL", "Query Optimization"
        ],
        "Data Engineering & Cloud": [
            "ETL", "ETL Pipelines", "Data Ingestion", "Data Preparation", "Azure", "Azure Databricks", "Databricks", "PySpark", "Power BI Fabric", "Medallion Architecture", "Data Pipelines"
        ],
        "BI, MIS & Reporting": [
            "Power BI", "DAX", "Power Query", "Power Automate", "RLS", "Row-Level Security", "Power BI Service", "Advanced Excel", "Excel", "MIS", "MIS Reporting", "KPI Reporting", "Dashboard", "Data Storytelling", "Report Automation"
        ],
        "Process & Data Quality": [
            "Data Validation", "Data Reconciliation", "Data Cleaning", "Root Cause Analysis", "Stakeholder Management", "SOPs", "Documentation", "Business Insights"
        ],
    },
    "core_skills": [
        # Programming & Databases
        "Python",
        "Pandas",
        "NumPy",
        "Openpyxl",
        "SQL",
        "SQL Server",
        "MySQL",
        "SSMS",
        "SSIS",
        # BI & Reporting & MIS
        "Power BI",
        "DAX",
        "Power Query",
        "Power Automate",
        "Row-Level Security",
        "RLS",
        "Power BI Service",
        "Power BI Fabric",
        "Advanced Excel",
        "Excel",
        "MIS",
        "MIS Reporting",
        "KPI Reporting",
        "Dashboard",
        "Data Storytelling",
        "Reporting Automation",
        # Data Engineering
        "ETL",
        "ETL Pipelines",
        "Data Ingestion",
        "Data Preparation",
        "Azure",
        "Azure Databricks",
        "Databricks",
        "PySpark",
        "Medallion Architecture",
        # ML, DL & GenAI
        "Machine Learning",
        "Scikit-learn",
        "Matplotlib",
        "Seaborn",
        "TensorFlow",
        "PyTorch",
        "spaCy",
        "Keras",
        "Deep Learning",
        "NLP",
        "LSTM",
        "CNN",
        "Transformers",
        "Self-Attention",
        "Generative AI",
        "GenAI",
        "LLMs",
        "Prompt Engineering",
        "Agentic Workflows",
        "MCP Connectors",
        # Analytics & Operations
        "Data Validation",
        "Data Reconciliation",
        "Root Cause Analysis",
        "Data Consolidation",
        "Stakeholder Management",
        "Documentation",
        "SOPs",
    ],
    "education": {
        "degree": "B.Sc. (Mathematics, Physics & Computer Science)",
        "college": "Vasundara Degree College",
        "graduation_year": "2019",
        "percentage": "64%",
    },
    "resume_text": """ADITHYA KRISHNA
AI/ML Engineer | Python | Machine Learning | Deep Learning | Generative AI
Email: adithyakrishna810@gmail.com | Mobile: 9177059799
Location: Hyderabad, 500047 | LinkedIn: linkedin.com/in/adithya-krishna-6aa058162

SUMMARY
Data professional with 4.5 years of experience in analytics, ETL, and reporting automation, now moving into AI/ML engineering. Strong Python foundation (NumPy, Pandas, Matplotlib) with hands-on machine learning, Generative AI, and agentic-workflow experience. Skilled at preparing, validating, and reconciling large multi-source datasets, building SQL/Azure data pipelines, and automating processes (up to 80% less manual effort). Eager to apply this data foundation to building and deploying deep learning and NLP models.

TECHNICAL SKILLS
ML Libraries & Packages: Scikit-learn, NumPy, Pandas, Matplotlib, Seaborn, TensorFlow
Deep Learning Frameworks: PyTorch, spaCy, Keras (working knowledge)
Deep Learning Architectures: LSTM, CNN, Self-Attention and Transformers (foundational knowledge)
Generative AI & Agentic Workflows: LLMs, prompt engineering, Python-based agentic workflows for scheduled task automation, debugging and modifying workflows with GenAI tools, MCP connectors
Programming & Databases: Python (Pandas, NumPy, Openpyxl), SQL, SQL Server, SSMS, SSIS
Data Engineering: ETL pipelines, data ingestion and preparation, Azure Databricks, PySpark, Power BI Fabric, medallion architecture
BI & Reporting: Power BI (DAX, Power Query, Power Automate, RLS, Power BI Service), Advanced Excel, KPI reporting, data storytelling
Process & Stakeholder Management: Translating business needs into data solutions, identifying key findings and profit-impact areas, documentation and SOPs

PROFESSIONAL EXPERIENCE
Deloitte — Data Analyst / Insights Analyst | Jun 2025 – Jun 2026
- Designed and deployed 8+ automated reporting workflows using Power Query and Power Automate, reducing manual reporting effort by approximately 80%.
- Built and maintained SQL-based transformation workflows to cleanse, standardize, validate, and reconcile client data across multiple business units, producing analysis-ready datasets.
- Supported enterprise data initiatives involving Azure, ETL/data pipelines, PySpark, and medallion architecture practices.
- Analyzed operational data to identify trends, exceptions, and actionable insights for business stakeholders.
- Performed data validation and root-cause analysis for data-quality issues, coordinating corrective actions to maintain accuracy.
- Translated stakeholder requirements into dashboards and KPI reports using Power BI, DAX, and row-level security.
- Maintained SOPs and documentation and supported knowledge transfer for new team members.

NTT DATA — HC Operations Analyst | Dec 2022 – Jan 2024
- Developed 5+ Power BI and Excel reports for production-quality metrics, giving timely visibility into operational KPIs and performance trends.
- Engineered Power Query transformation workflows to standardize client datasets and improve data quality.
- Performed root-cause analysis of production issues and coordinated corrective actions with clients and internal teams.

Optum Global Solutions — Claims Reporting Analyst | Aug 2020 – Nov 2022
- Consolidated multi-source Excel data into centralized Power BI and Excel dashboards, reducing client-reporting turnaround time by 50%.
- Designed data extraction and transformation workflows for claims data, improving consistency and quality across 15+ client reports.
- Prepared scheduled daily, weekly, and monthly consolidated production reports to support stakeholder decision-making.

Livasys Technologies — Digital Marketing Intern | Dec 2019 – Jun 2020
- Supported SEO content optimization with Yoast, applying keyword research and on-page SEO practices.

ACHIEVEMENTS
- Automated a daily scheduled report with Power Query, cutting a roughly six-hour manual process to five minutes (120x faster).
- Identified the root cause of a recurring claim-rejection denial-code issue, reducing analysis workload by 35%.

PROJECTS
- Laptop Price Prediction | Python, Pandas, NumPy, Scikit-learn: Built a machine-learning regression model to predict laptop prices from product specifications, including data cleaning, feature preparation, and model evaluation.
- Crime Data Analysis | MySQL, Python, Pandas, Matplotlib: Analyzed crime datasets with MySQL and Python to identify key trends and generate actionable insights.
- Sales Data Analysis Dashboard | Power BI: Built an interactive dashboard to visualize sales KPIs and performance trends; the analysis contributed to a reported 10% increase in sales performance.
- Coffee Company Data Analysis | Power BI: Built a dashboard analyzing coffee production and customer preferences to identify the key factors that drive satisfaction and sales.

CERTIFICATIONS
- Data Science — OdinSchool (Data Analysis, Python, Machine Learning Models, Generative AI)
- Introduction to LLM, Gen AI and Agentic AI — Sololearn (2026)
- Digital Marketing Certification

EDUCATION
- B.Sc. (Mathematics, Physics & Computer Science) | Vasundara Degree College | 2019 | 64%
- Intermediate | Sri Chaitanya | 2015 | 53%
- Schooling | St. Little Theresa's High School | 2012 | 6.8 CGPA

LANGUAGES
Telugu (Native) | English (Fluent) | Hindi (Conversational)
""",
}

# Official Company Career Site URLs and ATS Portal Adapters for companies in Company name.xlsx
OFFICIAL_COMPANY_PORTALS = {
    "deloitte": {
        "name": "Deloitte",
        "careers_url": "https://usijobs.deloitte.com/careersUSI/SearchJobs/Data%20Analyst%20Python%20Power%20BI",
        "search_api_type": "deloitte_phenom",
        "ats_type": "successfactors",
    },
    "capgemini": {
        "name": "Capgemini",
        "careers_url": "https://www.capgemini.com/in-en/careers/join-capgemini/job-search/?search_term=Data+Analyst+Power+BI+Python+SQL",
        "search_api_type": "capgemini_wp",
        "ats_type": "successfactors",
    },
    "infosys": {
        "name": "Infosys",
        "careers_url": "https://career.infosys.com/joblist?countrycode=IN&searchKey=Data%20Analyst%20Python%20Power%20BI",
        "search_api_type": "infosys_portal",
        "ats_type": "infosys",
    },
    "cognizant": {
        "name": "Cognizant",
        "careers_url": "https://careers.cognizant.com/india-en/jobs/?keyword=Data+Analyst+Power+BI+MIS&location=India",
        "search_api_type": "cognizant_phenom",
        "ats_type": "workday",
    },
    "randstad": {
        "name": "Randstad",
        "careers_url": "https://www.randstad.in/jobs/q-data-analyst/",
        "search_api_type": "randstad",
        "ats_type": "randstad",
    },
    "ntt data": {
        "name": "NTT DATA",
        "careers_url": "https://careers.services.global.ntt/global/en/search-results?keywords=Data%20Analyst%20Power%20BI%20Python",
        "search_api_type": "nttdata_phenom",
        "ats_type": "workday",
    },
    "indium": {
        "name": "Indium Software",
        "careers_url": "https://www.indium.tech/careers/",
        "search_api_type": "indium",
        "ats_type": "zoho_recruit",
    },
    "wipro": {
        "name": "Wipro",
        "careers_url": "https://careers.wipro.com/search/?q=Data+Analyst+MIS+Power+BI&locationsearch=India",
        "search_api_type": "wipro",
        "ats_type": "icims",
    },
    "techmahindra": {
        "name": "Tech Mahindra",
        "careers_url": "https://careers.techmahindra.com/Currentopportunity.aspx",
        "search_api_type": "techmahindra",
        "ats_type": "techmahindra",
    },
    "optum": {
        "name": "Optum (UnitedHealth Group)",
        "careers_url": "https://careers.unitedhealthgroup.com/job-search-results/?keyword=Data%20Analyst%20Reporting%20Power%20BI&country=IN",
        "search_api_type": "optum",
        "ats_type": "workday",
    },
    "accenture": {
        "name": "Accenture",
        "careers_url": "https://www.accenture.com/in-en/careers/jobsearch?jk=Data%20Analyst%20AI%20Python%20Power%20BI",
        "search_api_type": "accenture",
        "ats_type": "workday",
    },
    "ey": {
        "name": "EY (Ernst & Young)",
        "careers_url": "https://careers.ey.com/ey/search/?q=Data+Analyst+Power+BI+Python+India",
        "search_api_type": "ey",
        "ats_type": "successfactors",
    },
}
