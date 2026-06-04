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
df_exclude_object.shape

# --- CELL 7 ---
df_exclude_object.head(5)

# --- CELL 8 ---
from sklearn.model_selection import train_test_split
X = df_exclude_object.iloc[:,:-1]
y = df['Label']

# --- CELL 9 ---
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=101)

# --- CELL 10 ---
# Sample figsize in inches
fig, ax = plt.subplots(figsize=(20,10))
# Imbalanced DataFrame Correlation
corr = df_exclude_object.corr()
sns.heatmap(corr, cmap='YlGnBu', annot_kws={'size':30}, ax=ax)
ax.set_title("Imbalanced Correlation Matrix", fontsize=14)
plt.show()

# --- CELL 12 ---
from sklearn.model_selection import StratifiedKFold

# --- CELL 13 ---
kf = StratifiedKFold(n_splits=10)
kfolds = kf.split(X_train, y_train)
scores = []

# --- CELL 16 ---
from sklearn.linear_model import LogisticRegression
logmodel = LogisticRegression(max_iter=3000)

# --- CELL 17 ---
for k, (train, test) in enumerate(kfolds):
    logmodel.fit(X_train.iloc[train, :], y_train.iloc[train])
    score = logmodel.score(X_train.iloc[test, :], y_train.iloc[test])
    scores.append(score)
    print('Fold: %2d, Training/Test Split Distribution: %s, Accuracy: %.3f' % (k+1, np.bincount(y_train.iloc[train]), score))

print('\n\nCross-Validation accuracy: %.3f +/- %.3f' %(np.mean(scores), np.std(scores)))

# --- CELL 18 ---
logmodel.fit(X_train, y_train)

# --- CELL 19 ---
predLR = logmodel.predict(X_test)

# --- CELL 20 ---
from sklearn.metrics import classification_report, confusion_matrix
print(classification_report(y_test, predLR))

# --- CELL 21 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predLR)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 23 ---
#KNN
from sklearn.neighbors import KNeighborsClassifier

# --- CELL 24 ---
knn = KNeighborsClassifier()

# --- CELL 25 ---
knn.fit(X_train, y_train)

# --- CELL 26 ---
predKNN = knn.predict(X_test)

# --- CELL 27 ---
print(classification_report(y_test, predKNN))

# --- CELL 28 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predKNN)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 30 ---
from sklearn.tree import DecisionTreeClassifier

# --- CELL 31 ---
dtree = DecisionTreeClassifier()

# --- CELL 32 ---
dtree.fit(X_train,y_train)

# --- CELL 33 ---
predDtree = dtree.predict(X_test)

# --- CELL 34 ---
from sklearn.metrics import classification_report, confusion_matrix

# --- CELL 35 ---
print(classification_report(y_test, predDtree))

# --- CELL 36 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predDtree)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 37 ---
from sklearn.ensemble import RandomForestClassifier

# --- CELL 38 ---
rfc = RandomForestClassifier()

# --- CELL 39 ---
rfc.fit(X_train, y_train)

# --- CELL 40 ---
predRFC = rfc.predict(X_test)

# --- CELL 41 ---
print(classification_report(y_test, predRFC))

# --- CELL 42 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predRFC)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 44 ---
from sklearn.naive_bayes import GaussianNB

# --- CELL 45 ---
# Build a Gaussian Classifier
nbgc = GaussianNB()

# --- CELL 46 ---
# Model training
nbgc.fit(X_train, y_train)

# Predict Output
predNBGC = nbgc.predict(X_test)

# --- CELL 47 ---
print(classification_report(y_test, predNBGC))

# --- CELL 48 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predNBGC)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 50 ---
from sklearn.svm import SVC

# --- CELL 51 ---
svc = SVC()
'''
generalization:
low C = high bias, low variance
high C = low bias, low variance

low gamma = high variance
high gamma = low variance

gamma ada tergantung rbf
'''

# --- CELL 52 ---
svc.fit(X_train, y_train)

# --- CELL 53 ---
pred_svc = svc.predict(X_test)

# --- CELL 54 ---
print(classification_report(y_test, pred_svc))

# --- CELL 55 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, pred_svc)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');
