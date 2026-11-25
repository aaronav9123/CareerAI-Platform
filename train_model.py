import pandas as pd
import pickle

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

# ---------------- LOAD DATA ----------------
df = pd.read_excel("career_dataset_large.xlsx")

print("Dataset Loaded Successfully")
print(df.head())

# ---------------- ENCODE COLUMNS ----------------
encoders = {}

categorical_columns = [
    "Education Level",
    "Specialization",
    "Skills",
    "Certifications"
]

for col in categorical_columns:
    le = LabelEncoder()
    df[col] = le.fit_transform(df[col].astype(str))
    encoders[col] = le

# Encode Target
target_encoder = LabelEncoder()
df["Recommended Career"] = target_encoder.fit_transform(
    df["Recommended Career"].astype(str)
)

# ---------------- INPUT & OUTPUT ----------------
X = df[
    [
        "Education Level",
        "Specialization",
        "Skills",
        "Certifications",
        "CGPA/Percentage"
    ]
]

y = df["Recommended Career"]

# ---------------- TRAIN TEST SPLIT ----------------
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42
)

# ---------------- TRAIN MODEL ----------------
model = RandomForestClassifier(
    n_estimators=200,
    random_state=42
)

model.fit(X_train, y_train)

# ---------------- ACCURACY ----------------
pred = model.predict(X_test)

print("Accuracy :", accuracy_score(y_test, pred))

# ---------------- SAVE FILES ----------------
pickle.dump(model, open("model.pkl", "wb"))
pickle.dump(encoders, open("encoders.pkl", "wb"))
pickle.dump(target_encoder, open("target_encoder.pkl", "wb"))

print("Model Saved Successfully!")