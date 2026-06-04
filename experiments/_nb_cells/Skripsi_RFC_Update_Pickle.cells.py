# --- CELL 1 ---
from google.colab import drive
drive.mount('/content/drive')

# --- CELL 5 ---
import pandas as pd
import numpy as np

df = pd.read_csv("/content/drive/MyDrive/Skripsi/Preprocessing/notebooks_skripsi/TEKNIK2024_Datasets.csv", low_memory=False)
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)

# Making sure there are no 'Unmarked' features imported
df = df.loc[:, 'time_spent':]
df.head(10)

# --- CELL 7 ---
df[['Activity','Target']].value_counts(dropna=False)


# --- CELL 8 ---
df[['Target']].value_counts(dropna=False)

# --- CELL 10 ---
cleaned_df = df.dropna(subset=['Activity','Target'])
cleaned_df[['Activity','Target']].value_counts(dropna=False)
cleaned_df[['Target']].value_counts(dropna=False)

# --- CELL 14 ---
from imblearn.under_sampling import RandomUnderSampler

# Initialize the RandomUnderSampler
rus = RandomUnderSampler(random_state=42)


# --- CELL 16 ---
# Assuming df is your DataFrame and 'Target' is your target column
X = cleaned_df.drop('Target', axis=1)  # Features
y = cleaned_df['Target']  # Target variable

# Fit and apply the undersampling
X_resampled, y_resampled = rus.fit_resample(X, y)

# Convert the undersampled data back to a DataFrame if needed
undersampled_df = pd.DataFrame(X_resampled, columns=X.columns)
undersampled_df['Target'] = y_resampled

print('\n',undersampled_df['Target'].value_counts())

# --- CELL 18 ---
#remember that the 'Target' and 'Activity' class is already a string/object, so it is dropped automatically here
undersampled_num_df = undersampled_df.select_dtypes(exclude=['object'])

# --- CELL 21 ---
from sklearn.model_selection import train_test_split

# Assuming 'Target' is your target variable
X = undersampled_num_df  # Features
y = undersampled_df['Target']  # Target variable

# Split the data into train and test sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# --- CELL 23 ---
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix

rfc = RandomForestClassifier()

# Train the classifier
rfc.fit(X_train, y_train)

# Make predictions on the test set
y_pred = rfc.predict(X_test)

# Evaluate the classifier
print("RANDOM FOREST CLASSIFIER\n")
print("Confusion Matrix:\n", confusion_matrix(y_test, y_pred))
print("\nClassification Report:\n", classification_report(y_test, y_pred))

# --- CELL 26 ---
from sklearn.metrics import accuracy_score
from matplotlib import pyplot as plt

train_scores, test_scores = list(), list()
# define the tree depths to evaluate
values = [i for i in range(1, 20)]
# evaluate a decision tree for each depth
for i in values:
 # configure the model
 model = RandomForestClassifier(n_estimators=i)
 # fit model on the training dataset
 model.fit(X_train, y_train)
 # evaluate on the train dataset
 train_yhat = model.predict(X_train)
 train_acc = accuracy_score(y_train, train_yhat)
 train_scores.append(train_acc)
 # evaluate on the test dataset
 test_yhat = model.predict(X_test)
 test_acc = accuracy_score(y_test, test_yhat)
 test_scores.append(test_acc)
 # summarize progress
 print('>%d, train: %.3f, test: %.3f' % (i, train_acc, test_acc))
# plot of train and test scores vs number of neighbors
plt.plot(values, train_scores, '-o', label='Train')
plt.plot(values, test_scores, '-o', label='Test')
plt.legend()
plt.show()

# --- CELL 28 ---
from sklearn.model_selection import cross_val_score
# Perform k-fold cross-validation on the training data
cv_scores = cross_val_score(rfc, X_train, y_train, cv=5)

# Print the cross-validation scores
print("Cross-Validation Scores:", cv_scores)
print("Mean CV Accuracy:", np.mean(cv_scores))
print("Standard Deviation of CV Accuracy:", np.std(cv_scores))

# --- CELL 31 ---
from matplotlib import pyplot as plt
# get importance
importance = rfc.feature_importances_
feature_names = undersampled_num_df.columns
threshold_max_importance_score = 0.100

for i, (feature, score) in enumerate(zip(feature_names, importance)):
    print('Feature:', feature, 'Score:', score)

# Plot feature importance
plt.figure(figsize=(14, 6))

# Plot feature importance
bars = plt.bar(feature_names, importance)
asdf
# Add color to bars exceeding the threshold
for bar, score in zip(bars, importance):
    if score > threshold_max_importance_score:
        bar.set_color('red')  # Set color to red for bars exceeding the threshold

plt.axhline(y=threshold_max_importance_score, color='r', linestyle='--', label='Threshold')  # Add threshold line
plt.xlabel('Feature')
plt.ylabel('Importance Score')
plt.title('Feature Importance')
plt.xticks(rotation=90)  # Rotate x-axis labels for better readability
plt.tight_layout()  # Adjust layout to prevent clipping of labels
plt.show()

# Calculate mean importance score
mean_importance = sum(importance) / len(importance)
print("Mean importance score:", mean_importance)


# --- CELL 33 ---

#we dropped the highest exceeding features
selected_features = undersampled_num_df.drop(['time_spent','responp'], axis = 1)
feature_names = selected_features.columns
y = undersampled_df['Target']  # Target variable
from sklearn.ensemble import RandomForestClassifier

# Assuming you've already imported necessary libraries and defined threshold_max_importance_score

# Train RandomForestClassifier on the selected features
rfc_selected = RandomForestClassifier()
rfc_selected.fit(selected_features, y)  # Assuming target_variable is defined elsewhere

# Get importance scores for the selected features
importance_selected = rfc_selected.feature_importances_

# Plot feature importance for selected features
plt.figure(figsize=(14, 6))

# Plot feature importance
bars = plt.bar(feature_names, importance_selected)  # Use importance_selected instead of importance

# Add color to bars exceeding the threshold
for bar, score in zip(bars, importance_selected):
    if score > threshold_max_importance_score:
        bar.set_color('red')  # Set color to red for bars exceeding the threshold

plt.axhline(y=threshold_max_importance_score, color='r', linestyle='--', label='Threshold')  # Add threshold line
plt.xlabel('Feature')
plt.ylabel('Importance Score')
plt.title('Feature Importance (Selected Features)')
plt.xticks(rotation=90)  # Rotate x-axis labels for better readability
plt.tight_layout()  # Adjust layout to prevent clipping of labels
plt.show()

# Calculate mean importance score for selected features
mean_importance_selected = sum(importance_selected) / len(importance_selected)
print("Mean importance score for selected features:", mean_importance_selected)



# --- CELL 35 ---

# Assuming 'Target' is your target variable
X = undersampled_num_df.drop(['time_spent','responp'], axis = 1) # Features
y = undersampled_df['Target']  # Target variable

# Split the data into train and test sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

rfc = RandomForestClassifier()

# Train the classifier
rfc.fit(X_train, y_train)

# Make predictions on the test set
y_pred = rfc.predict(X_test)

# Evaluate the classifier
print("[NEW] RANDOM FOREST CLASSIFIER\n")
print("Confusion Matrix:\n", confusion_matrix(y_test, y_pred))
print("\nClassification Report:\n", classification_report(y_test, y_pred))

# --- CELL 36 ---
import pickle
filename = '/content/drive/MyDrive/Skripsi/Preprocessing/notebooks_skripsi/rfc_pickle.sav'
pickle.dump(rfc, open(filename, 'wb'))

# --- CELL 37 ---
# load the model from disk
loaded_model = pickle.load(open(filename, 'rb'))
result = loaded_model.score(X_test, y_test)
print(result)
