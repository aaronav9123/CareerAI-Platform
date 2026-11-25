import pickle

columns = pickle.load(open("columns.pkl", "rb"))

print(columns)
print(type(columns))
print(len(columns))