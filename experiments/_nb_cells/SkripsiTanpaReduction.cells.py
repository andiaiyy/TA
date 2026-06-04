# --- CELL 0 ---
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

# --- CELL 1 ---
df = pd.read_csv('/content/drive/MyDrive/ALLFLOWMETER_HIKARI2021.csv')

# --- CELL 2 ---
df.drop(['Unnamed: 0', 'Unnamed: 0.1'], axis = 1, inplace=True)

# --- CELL 3 ---
df_exclude_object = df.select_dtypes(exclude=['object'])

# --- CELL 4 ---
X = df_exclude_object.iloc[:,:-1]
y = df_exclude_object.iloc[:,-1]

# --- CELL 5 ---
from sklearn.model_selection import train_test_split

# --- CELL 6 ---
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=101)

# --- CELL 7 ---
from sklearn.linear_model import LogisticRegression
logmodel = LogisticRegression(max_iter=7600, solver='lbfgs')

# --- CELL 8 ---
logmodel.fit(X_train, y_train)

# --- CELL 9 ---
predictions = logmodel.predict(X_test)

# --- CELL 10 ---
#LinearRegression max iter 7600, data belum dibalance
from sklearn.metrics import classification_report
print(classification_report(y_test, predictions))

# --- CELL 11 ---
#LinearRegression max iter 3000, data belum dibalance
from sklearn.metrics import classification_report
print(classification_report(y_test, predictions))

# --- CELL 13 ---
y.value_counts()

# --- CELL 14 ---
sns.countplot(x='Label', data=df_exclude_object)

# --- CELL 15 ---
sns.countplot(x='traffic_category', data=df)

# --- CELL 16 ---
from collections import Counter
#https://towardsdatascience.com/how-to-balance-a-dataset-in-python-36dff9d12704
print(f"Training target statistics: {Counter(y_train)}")
print(f"Testing target statistics: {Counter(y_test)}")

# --- CELL 17 ---
from imblearn.under_sampling import RandomUnderSampler
under_sampler = RandomUnderSampler(random_state=42)
X_res, y_res = under_sampler.fit_resample(X_train, y_train)
print(f"Training target statistics: {Counter(y_res)}")
print(f"Testing target statistics: {Counter(y_test)}")

# --- CELL 18 ---
logmodel.fit(X_res, y_res)

# --- CELL 19 ---
predictions = logmodel.predict(X_test)

# --- CELL 20 ---
#LinearRegression max iter 7600, data dibalance
from sklearn.metrics import classification_report
print(classification_report(y_test, predictions))

# --- CELL 21 ---
#LinearRegression max iter 3000, data dibalance
from sklearn.metrics import classification_report
print(classification_report(y_test, predictions))

# --- CELL 22 ---
from imblearn.under_sampling import NearMiss
under_sampler = NearMiss()
X_res, y_res = under_sampler.fit_resample(X_train, y_train)
print(f"Training target statistics: {Counter(y_res)}")
print(f"Testing target statistics: {Counter(y_test)}")

# --- CELL 24 ---
from sklearn.metrics import confusion_matrix

# --- CELL 25 ---
confusion_matrix(y_test, predictions)

# --- CELL 26 ---
confusion_matrix(y_test, predictions)

# --- CELL 27 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predictions)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 29 ---
from sklearn.model_selection import KFold, cross_val_score

# --- CELL 30 ---

k_folds = KFold(n_splits = 10)

scores = cross_val_score(logmodel, X, y, cv = k_folds)

print("Cross Validation Scores: ", scores)
print("Average CV Score: ", scores.mean())
print("Number of CV Scores used in Average: ", len(scores))
