# Elevator Maintenance Optimization System

This project is a capstone-level elevator maintenance and breakdown scheduling system.  
It combines a Django REST backend, Flutter web/mobile interfaces, and an optimization engine to assign technicians to maintenance and callback tasks more efficiently.

The main goal of the system is to help elevator maintenance operations by improving technician scheduling, route planning, workload balance, and emergency callback handling.

---

## Project Overview

Elevator maintenance companies need to assign technicians to many different tasks such as planned maintenance, repair jobs, and urgent callback incidents. Manual planning can become inefficient when there are many technicians, elevators, locations, priority levels, and daily workload constraints.

This system solves that problem by generating optimized technician schedules based on:

- Technician availability
- Technician skills and specialty
- Elevator location
- Maintenance task requirements
- Callback and breakdown priority
- Travel time and distance
- Workload balance
- Supervisor regions and technician groups
- Emergency response requirements

The system includes:

- Admin web panel
- Supervisor dashboard
- Technician mobile interface
- Django REST backend
- Optimization workflow
- Route and map support
- Maintenance and callback scheduling logic

---

## Main Purpose

The purpose of this project is to demonstrate how optimization, backend APIs, and web/mobile interfaces can be combined to create a practical maintenance planning platform.

The project shows:

- Full-stack system architecture
- Role-based user interfaces
- Optimization-based technician assignment
- Route-aware scheduling
- Emergency callback prioritization
- Maintenance and repair workflow management
- Realistic supervisor and technician operations

Although this is an academic capstone project, the system structure represents a realistic elevator maintenance scheduling platform.

---

## Main Features

## 1. Admin Web Panel

The admin panel is used to control the global schedule generation process.

Admin features include:

- Generate schedules for a selected date range
- Start clean schedule generation
- Observe generation progress
- Trigger backend scheduling commands
- Manage full simulation workflow
- Generate maintenance and callback schedules
- Monitor whether schedule generation is running

When the admin presses the generate schedule button, the frontend sends a request to the Django backend. The backend then starts the schedule generation process, prepares tasks, runs the optimizer, and saves the generated schedules into the database.

---

## 2. Supervisor Dashboard

The supervisor dashboard is used by regional supervisors to monitor technicians, units, and scheduled work.

Supervisor features include:

- View technician schedules
- View maintenance tasks
- View callback and repair incidents
- Add new technicians
- Track daily reports
- Track monthly logs
- View unit history
- Monitor technician workload
- Manage leave and availability information
- Review assigned jobs by date and region

Supervisors are responsible for managing their assigned technician groups and following the operational state of elevator units.

---

## 3. Technician Mobile App

The technician mobile interface is designed for field technicians.

Technician features include:

- Technician login
- View daily assigned jobs
- View task details
- Follow assigned task order
- Access elevator and unit information
- Update task status
- View maintenance or repair-related information
- Complete assigned field work

The mobile app represents the real field workflow of technicians who receive daily schedules and complete assigned elevator tasks.

---

## 4. Maintenance Scheduling

The system generates planned maintenance schedules for elevator units.

Maintenance scheduling considers:

- Elevator units
- Technician groups
- Maintenance intervals
- Technician availability
- Skill compatibility
- Workload distribution
- Travel distance and time
- Daily capacity limits

The goal is not only to assign tasks, but also to create a balanced and realistic schedule for technicians.

---

## 5. Callback and Breakdown Scheduling

The system also supports callback and breakdown incidents.

Callback tasks can represent urgent or normal failures. These tasks are handled differently from planned maintenance because emergency work may have higher priority and stricter response requirements.

Callback priority examples:

- AA: Highest priority emergency
- A: Very urgent
- B: Normal callback priority
- C: Lower urgency
- D: Lowest priority

Emergency callbacks are prioritized more strongly by the optimization model.

---

## Optimization System

The project uses an optimization-based scheduling approach.

The optimizer considers:

- Task priority
- Technician-task compatibility
- Estimated service duration
- Travel time
- Travel distance
- Technician workload
- Daily working limits
- Region and group constraints
- Emergency callback priority
- Maintenance requirements

The optimizer does not randomly assign tasks. It uses structured technician, task, and route data to generate a better schedule.

---

## Callback Priority Logic

Callback incidents can have different priority levels.

Example priority levels:

```text
AA = Highest priority emergency
A  = Very urgent
B  = Normal callback
C  = Lower urgency
D  = Lowest priority
```

In the simulation workflow, callback tasks can be generated as urgent or normal.  
AA callbacks are handled with higher importance than normal callback jobs.

The optimizer uses this priority information when assigning technicians and deciding which tasks should be handled first.

---

## Route and Map System

The system uses route and distance information to improve scheduling quality.

Route-related features include:

- Technician-to-task travel calculation
- Task-to-task travel calculation
- Route distance support
- Route geometry support
- Map-based schedule visualization
- Local route caching
- Reduced repeated external API calls

Route results are cached locally so the system does not repeatedly request the same route data.

Generated cache files are not stored in the GitHub repository.

---

## System Architecture

The system follows a full-stack architecture.

```text
Flutter Web / Flutter Mobile
        ↓
Django REST API
        ↓
Backend Business Logic
        ↓
Scheduling Services
        ↓
Optimization Commands
        ↓
Gurobi Optimizer
        ↓
Database
        ↓
Updated schedules shown in UI
```

### Frontend

The frontend is responsible for user interaction.

It includes:

- Admin web interface
- Supervisor web dashboard
- Technician mobile interface

The frontend sends requests to the backend and displays schedules, tasks, reports, and technician information.

### Backend

The backend is responsible for:

- API endpoints
- Authentication-related logic
- Task management
- Technician management
- Schedule generation
- Callback incident handling
- Reports and history
- Route and map services
- Optimization command execution

### Optimization Layer

The optimization layer is responsible for:

- Preparing task and technician data
- Preparing travel-time data
- Applying scheduling constraints
- Calling the solver
- Returning optimized assignments
- Writing results into the database

### Database

The database stores:

- Users
- Technicians
- Supervisors
- Elevator units
- Maintenance tasks
- Callback tasks
- Schedules
- Reports
- Unit history
- Leave requests
- Optimization results

---

## Schedule Generation Flow

The main schedule generation flow is:

```text
Admin presses Generate Schedule
        ↓
Frontend sends POST request to backend
        ↓
Backend starts schedule generation command
        ↓
Maintenance tasks are prepared
        ↓
Callback tasks are prepared
        ↓
Travel-time and distance data are loaded
        ↓
Optimizer assigns technicians
        ↓
Schedules are saved to database
        ↓
Admin and supervisors can view the result
```

This separates the user interface from the optimization process.  
The frontend only starts the process and observes the result.  
The backend performs the actual scheduling and optimization work.

---

## Technology Stack

## Backend

- Python
- Django
- Django REST Framework
- SQLite for local/demo database
- Gurobi optimization solver
- Pandas and data processing utilities

## Frontend

- Flutter
- Dart
- Flutter Web
- Flutter Mobile

## Optimization and Data

- Gurobi
- Custom scheduling logic
- Technician-task assignment model
- Travel-time and distance calculation
- Route geometry caching
- Maintenance and callback task generation

---

## Repository Structure

```text
Capstone/
│
├── api/                    # Django API views, services, and backend logic
├── lib/                    # Flutter source code
│   ├── mobile/             # Technician mobile app files
│   └── web/                # Admin and supervisor web interface files
│
├── data/                   # Project data files
├── assets/                 # Flutter assets
├── android/                # Flutter Android project files
├── ios/                    # Flutter iOS project files
├── web/                    # Flutter web project files
│
├── manage.py               # Django management entry point
├── requirements.txt        # Python backend dependencies
├── pubspec.yaml            # Flutter dependencies
├── README.md               # Project documentation
└── .gitignore              # Ignored local/generated files
```

---

## Demo Login Rules

For demo usage, the project uses simple fixed credential rules.

### Technician Accounts

Example technician usernames:

```text
t103
t403
```

Technician password:

```text
tech12345
```

### Supervisor Accounts

Example supervisor username format:

```text
ahmet.ylmaz
```

Supervisor password:

```text
sup12345
```

New technicians added from the supervisor dashboard should follow the same demo credential pattern.

---

## Local Setup

## 1. Clone the Repository

```bash
git clone https://github.com/Genkyu9988/Capstone.git
cd Capstone
```

---

## 2. Create and Activate Virtual Environment

For Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

---

## 3. Install Backend Requirements

```powershell
pip install -r requirements.txt
```

---

## 4. Run Django Migrations

```powershell
python manage.py migrate
```

---

## 5. Start the Django Backend

```powershell
python manage.py runserver
```

The backend will usually run on:

```text
http://127.0.0.1:8000
```

---

## 6. Install Flutter Dependencies

```powershell
flutter pub get
```

---

## 7. Run the Flutter App

For Flutter web:

```powershell
flutter run -d chrome
```

For Android emulator:

```powershell
flutter run
```

---

## Important Runtime Files

Some files are generated locally and should not be pushed to GitHub.

Ignored files include:

```text
db.sqlite3
.maps_cache/
.admin_jobs/
*.pid
```

These files may be created when running the backend, generating schedules, or caching route data.

They are ignored because:

- `db.sqlite3` is a local database file
- `.maps_cache/` contains generated route cache files
- `.admin_jobs/` contains runtime process/status files
- `.pid` files are local process files

---

## Git Notes

Before pushing changes, check the repository status:

```powershell
git status
```

Add and commit changes:

```powershell
git add .
git commit -m "Your commit message"
git push origin main
```

Avoid pushing generated local files such as:

```text
db.sqlite3
.maps_cache/
.admin_jobs/
```

---

## Example Workflow

A typical usage flow is:

```text
1. Admin logs into the web panel
2. Admin selects a date range
3. Admin presses Generate Schedule
4. Backend starts schedule generation
5. Maintenance and callback tasks are prepared
6. Optimizer assigns technicians
7. Schedules are saved into the database
8. Supervisors review schedules
9. Technicians view assigned tasks on mobile
10. Tasks are completed and reports/history are updated
```

---

## What Makes This Project Useful

This project is useful because it connects multiple real-world software engineering concepts:

- Backend API design
- Mobile and web frontend development
- Optimization modeling
- Scheduling automation
- Route-aware decision making
- Role-based workflows
- Database-backed task management
- Emergency prioritization
- System integration

Instead of being only a simple CRUD application, this project includes a decision-making optimization layer that produces operational schedules.

---

## Academic Value

This project demonstrates:

- Software engineering project design
- Full-stack development
- API integration
- Optimization-based problem solving
- Real-world constraint modeling
- Data-driven scheduling
- UI and backend integration
- Practical capstone implementation

The project can be explained from both a software architecture perspective and an optimization perspective.

---

## Future Improvements

Possible future improvements include:

- Real-time technician GPS tracking
- More advanced route optimization
- Live emergency callback insertion
- Better mobile task completion workflow
- Push notifications
- Supervisor analytics dashboard
- More detailed maintenance history
- Cloud database deployment
- Production authentication system
- More advanced reporting and export features

---

## Project Summary

Elevator Maintenance Optimization System is a full-stack capstone project that helps generate optimized schedules for elevator maintenance operations.

It combines:

- Django backend
- Flutter web/mobile frontend
- Gurobi optimization
- Route-aware scheduling
- Technician and supervisor workflows
- Maintenance and callback task management

The system shows how software engineering and optimization can work together to solve a realistic field-service scheduling problem.
