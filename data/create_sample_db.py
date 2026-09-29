"""Build the sample company database used to try the app.

Run directly to (re)create it:
    python data/create_sample_db.py
The app also calls create_sample_db() automatically if the file is missing.
"""

import sqlite3
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "company.db"

SCHEMA = """
CREATE TABLE departments (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    location  TEXT NOT NULL
);

CREATE TABLE employees (
    id             INTEGER PRIMARY KEY,
    first_name     TEXT NOT NULL,
    last_name      TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    job_title      TEXT NOT NULL,
    salary         INTEGER NOT NULL,
    hire_date      TEXT NOT NULL,          -- ISO date: YYYY-MM-DD
    department_id  INTEGER NOT NULL REFERENCES departments(id)
);

CREATE TABLE projects (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    budget         INTEGER NOT NULL,
    start_date     TEXT NOT NULL,
    end_date       TEXT,                   -- NULL means still running
    department_id  INTEGER NOT NULL REFERENCES departments(id)
);

CREATE TABLE employee_projects (
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    project_id   INTEGER NOT NULL REFERENCES projects(id),
    role         TEXT NOT NULL,
    PRIMARY KEY (employee_id, project_id)
);
"""

DEPARTMENTS = [
    (1, "Engineering", "Berlin"),
    (2, "Marketing", "London"),
    (3, "Sales", "London"),
    (4, "Finance", "Paris"),
    (5, "Human Resources", "Paris"),
    (6, "Customer Support", "Lisbon"),
]

# (id, first, last, job_title, salary, hire_date, department_id)
EMPLOYEES = [
    (1, "Alice", "Martin", "Engineering Manager", 98000, "2018-03-12", 1),
    (2, "Bruno", "Silva", "Senior Backend Engineer", 86000, "2019-07-01", 1),
    (3, "Chloe", "Nguyen", "Frontend Engineer", 72000, "2021-02-15", 1),
    (4, "Daniel", "Kowalski", "Data Engineer", 78000, "2020-11-09", 1),
    (5, "Emma", "Rossi", "Junior Engineer", 55000, "2023-09-04", 1),
    (6, "Farah", "Haddad", "Marketing Director", 91000, "2017-05-22", 2),
    (7, "George", "Brown", "Content Strategist", 58000, "2022-01-10", 2),
    (8, "Hana", "Sato", "SEO Specialist", 54000, "2022-06-20", 2),
    (9, "Ivan", "Petrov", "Marketing Analyst", 61000, "2021-08-30", 2),
    (10, "Julia", "Schmidt", "Sales Manager", 84000, "2018-10-01", 3),
    (11, "Karim", "Mansour", "Account Executive", 63000, "2020-04-14", 3),
    (12, "Laura", "Garcia", "Account Executive", 65000, "2019-12-02", 3),
    (13, "Mehdi", "Benali", "Sales Representative", 48000, "2023-03-27", 3),
    (14, "Nina", "Andersen", "Finance Manager", 88000, "2016-09-19", 4),
    (15, "Omar", "Khalil", "Accountant", 57000, "2021-05-17", 4),
    (16, "Paula", "Costa", "Financial Analyst", 62000, "2022-11-07", 4),
    (17, "Quentin", "Dubois", "HR Manager", 76000, "2019-01-28", 5),
    (18, "Rania", "Aziz", "Recruiter", 52000, "2023-06-12", 5),
    (19, "Samuel", "Okafor", "Support Lead", 60000, "2020-02-03", 6),
    (20, "Tara", "Walsh", "Support Agent", 42000, "2022-08-22", 6),
    (21, "Umar", "Farouk", "Support Agent", 41000, "2024-01-15", 6),
    (22, "Vera", "Ivanova", "DevOps Engineer", 80000, "2020-09-14", 1),
]

# (id, name, budget, start_date, end_date, department_id)
PROJECTS = [
    (1, "Website Redesign", 120000, "2024-01-15", "2024-09-30", 2),
    (2, "Mobile App", 250000, "2024-03-01", None, 1),
    (3, "Data Warehouse", 180000, "2023-06-01", "2024-05-31", 1),
    (4, "Spring Campaign", 45000, "2025-02-01", "2025-05-31", 2),
    (5, "CRM Migration", 95000, "2024-07-01", None, 3),
    (6, "Budget Automation", 60000, "2025-01-10", None, 4),
    (7, "Help Center Revamp", 38000, "2024-10-01", "2025-03-15", 6),
]

# (employee_id, project_id, role)
ASSIGNMENTS = [
    (1, 2, "Lead"), (2, 2, "Developer"), (3, 2, "Developer"), (22, 2, "DevOps"),
    (4, 3, "Lead"), (2, 3, "Developer"), (22, 3, "DevOps"),
    (6, 1, "Sponsor"), (7, 1, "Content"), (3, 1, "Developer"), (8, 1, "SEO"),
    (6, 4, "Lead"), (9, 4, "Analyst"), (7, 4, "Content"),
    (10, 5, "Lead"), (11, 5, "Contributor"), (4, 5, "Developer"),
    (14, 6, "Lead"), (16, 6, "Analyst"), (5, 6, "Developer"),
    (19, 7, "Lead"), (20, 7, "Contributor"), (8, 7, "SEO"),
]


def create_sample_db(path: Path = DEFAULT_PATH) -> Path:
    """Create (or overwrite) the sample database at `path` and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)

    employees = [
        (id_, first, last, f"{first}.{last}@example.com".lower(), title, salary, hired, dept)
        for id_, first, last, title, salary, hired, dept in EMPLOYEES
    ]

    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO departments VALUES (?, ?, ?)", DEPARTMENTS)
        conn.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?)", employees)
        conn.executemany("INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)", PROJECTS)
        conn.executemany("INSERT INTO employee_projects VALUES (?, ?, ?)", ASSIGNMENTS)
        conn.commit()
    finally:
        conn.close()
    return path


if __name__ == "__main__":
    print(f"Created {create_sample_db()}")
