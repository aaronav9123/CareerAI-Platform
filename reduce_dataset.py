
import pandas as pd
from sklearn.model_selection import train_test_split

# Load original dataset
df = pd.read_excel("career_dataset_large.xlsx")

print("Original dataset:", len(df))

# Select exactly 1000 records, preserving career proportions
sampled_df, _ = train_test_split(
    df,
    train_size=1000,
    stratify=df["Recommended Career"],
    random_state=42
)

# Save separately without overwriting the original
sampled_df.to_excel("career_dataset_1000.xlsx", index=False)

print("Reduced dataset:", len(sampled_df))
print("Reduced dataset saved successfully!")
