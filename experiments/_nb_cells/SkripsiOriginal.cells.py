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
df.shape

# --- CELL 4 ---
df_exclude_object = df.select_dtypes(exclude=['object'])

# --- CELL 5 ---
df_exclude_object['Label'].value_counts()

# --- CELL 6 ---
plt.pie(df_exclude_object['Label'].value_counts(), labels=['Bening', 'Malicious'], autopct='%.0f%%')

# --- CELL 7 ---
df_exclude_object.shape

# --- CELL 8 ---
df_exclude_object.head(5)

# --- CELL 9 ---
from sklearn.model_selection import train_test_split
X = df_exclude_object.iloc[:,:-1]
y = df['Label']

# --- CELL 10 ---
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=101)

# --- CELL 11 ---
# Sample figsize in inches
fig, ax = plt.subplots(figsize=(20,10))
# Imbalanced DataFrame Correlation
corr = df_exclude_object.corr()
sns.heatmap(corr, cmap='YlGnBu', annot_kws={'size':30}, ax=ax)
ax.set_title("Imbalanced Correlation Matrix", fontsize=14)
plt.show()

# --- CELL 14 ---
from sklearn.linear_model import LogisticRegression
logmodel = LogisticRegression(max_iter=3000)

# --- CELL 15 ---
logmodel.fit(X_train, y_train)

# --- CELL 16 ---
predLR = logmodel.predict(X_test)

# --- CELL 17 ---
from sklearn.metrics import classification_report, confusion_matrix
print(classification_report(y_test, predLR))

# --- CELL 18 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predLR)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 20 ---
#KNN
from sklearn.neighbors import KNeighborsClassifier

# --- CELL 21 ---
knn = KNeighborsClassifier()

# --- CELL 22 ---
knn.fit(X_train, y_train)

# --- CELL 23 ---
predKNN = knn.predict(X_test)

# --- CELL 24 ---
print(classification_report(y_test, predKNN))

# --- CELL 25 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predKNN)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 27 ---
from sklearn.tree import DecisionTreeClassifier

# --- CELL 28 ---
dtree = DecisionTreeClassifier()

# --- CELL 29 ---
dtree.fit(X_train, y_train)

# --- CELL 30 ---
predDtree = dtree.predict(X_test)

# --- CELL 31 ---
from sklearn.metrics import classification_report, confusion_matrix

# --- CELL 32 ---
print(classification_report(y_test, predDtree))

# --- CELL 33 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predDtree)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 34 ---
from sklearn.ensemble import RandomForestClassifier

# --- CELL 35 ---
rfc = RandomForestClassifier()

# --- CELL 36 ---
rfc.fit(X_train, y_train)

# --- CELL 37 ---
predRFC = rfc.predict(X_test)

# --- CELL 38 ---
print(classification_report(y_test, predRFC))

# --- CELL 39 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predRFC)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 41 ---
from sklearn.naive_bayes import GaussianNB

# --- CELL 42 ---
# Build a Gaussian Classifier
nbgc = GaussianNB()

# --- CELL 43 ---
# Model training
nbgc.fit(X_train, y_train)

# Predict Output
predNBGC = nbgc.predict(X_test)

# --- CELL 44 ---
print(classification_report(y_test, predNBGC))

# --- CELL 45 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predNBGC)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 47 ---
from sklearn.svm import SVC

# --- CELL 48 ---
svc = SVC()
'''
generalization:
low C = high bias, low variance
high C = low bias, low variance

low gamma = high variance
high gamma = low variance

gamma ada tergantung rbf
'''

# --- CELL 49 ---
svc.fit(X_train, y_train)

# --- CELL 50 ---
pred_svc = svc.predict(X_test)

# --- CELL 51 ---
print(classification_report(y_test, pred_svc))

# --- CELL 52 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, pred_svc)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');
