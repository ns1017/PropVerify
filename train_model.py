from sklearn.ensemble import RandomForestClassifier
import pickle
import config

# Synthetic data: [latitude, age, damage] -> good candidate (1) or not (0)
X = [
    [30, 20, 0],  # Sunny, new, no damage -> good
    [45, 50, 1],  # Northern, old, damaged -> bad
    [35, 30, 0],  # Moderate, average, no damage -> good
    [60, 10, 0]   # Far north, new, no damage -> bad
]
y = [1, 0, 1, 0]

model = RandomForestClassifier(n_estimators=10, random_state=42)
model.fit(X, y)

with open(config.MODEL_PATH, 'wb') as f:
    pickle.dump(model, f)

print(f"Model saved to {config.MODEL_PATH}")