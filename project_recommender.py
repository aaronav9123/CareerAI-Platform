"""
project_recommender.py
-----------------------
Looks up beginner/intermediate/advanced project recommendations for a
predicted career from data/project_recommendations.json.
"""

import json
import os

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "project_recommendations.json")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    PROJECT_RECOMMENDATIONS = json.load(f)

GENERIC_PROJECTS = {
    "beginner": [
        {"title": "Skills Portfolio Document", "description": "Put together a one-page summary of your skills, education and interests.", "skills_learned": ["Communication"]}
    ],
    "intermediate": [
        {"title": "Mini Case Study", "description": "Pick a real-world problem in your field of interest and outline how you'd approach it.", "skills_learned": ["Problem Solving"]}
    ],
    "advanced": [
        {"title": "End-to-End Capstone", "description": "Choose a substantial project in your target field and see it through from plan to finished result.", "skills_learned": ["Problem Solving", "Communication"]}
    ]
}


def get_projects(career):
    return PROJECT_RECOMMENDATIONS.get(career, GENERIC_PROJECTS)
