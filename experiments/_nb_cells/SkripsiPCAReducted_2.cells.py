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
# Sample figsize in inches
fig, ax = plt.subplots(figsize=(20,10))
# Imbalanced DataFrame Correlation
corr = df_exclude_object.corr()
sns.heatmap(corr, cmap='YlGnBu', annot_kws={'size':30}, ax=ax)
ax.set_title("Imbalanced Correlation Matrix", fontsize=14)
plt.show()

# --- CELL 10 ---
#pake PCA utk cari 2 principle components
from sklearn.preprocessing import StandardScaler

# --- CELL 11 ---
#kita mau pastikan setiap feature kita itu hanya single unit variance
scaler = StandardScaler()
scaler.fit(df_exclude_object.iloc[:,:-1])

# --- CELL 12 ---
scaled_data = scaler.transform(df_exclude_object.iloc[:,:-1])

# --- CELL 15 ---
#PCA
from sklearn.decomposition import PCA

# --- CELL 16 ---
pca_2 = PCA(n_components = 2) #mencari 2 principle components

# --- CELL 17 ---
pca_2.fit(scaled_data)

# --- CELL 18 ---
x_pca_2 = pca_2.transform(scaled_data)

# --- CELL 19 ---
scaled_data.shape

# --- CELL 20 ---
x_pca_2.shape

# --- CELL 21 ---
plt.figure(figsize=(10,6))
plt.scatter(x_pca_2[:, 0], x_pca_2[:, 1], c=df['Label'], cmap = 'viridis')
plt.xlabel('First Principle Component')
plt.ylabel('Second Principle Component')

# --- CELL 22 ---
pca_2.components_

# --- CELL 23 ---
df_comp = pd.DataFrame(pca_2.components_, columns=df_exclude_object.iloc[:,:-1].columns)

# --- CELL 24 ---
plt.figure(figsize = (12,6))
sns.heatmap(df_comp, cmap='plasma')

# --- CELL 25 ---
# plot a scree plot
plt.plot(np.cumsum(pca_2.explained_variance_ratio_))
plt.xlabel('Number of Features')
plt.ylabel('Explained Variance')

# --- CELL 27 ---
pca = PCA(n_components = 22) #mencari 2 principle components

# --- CELL 28 ---
pca.fit(scaled_data)

# --- CELL 29 ---
x_pca = pca.transform(scaled_data)

# --- CELL 30 ---
scaled_data.shape

# --- CELL 31 ---
x_pca.shape

# --- CELL 32 ---
pca.components_

# --- CELL 33 ---
df_comp = pd.DataFrame(pca.components_, columns=df_exclude_object.iloc[:,:-1].columns)

# --- CELL 34 ---
plt.figure(figsize = (12,6))
sns.heatmap(df_comp, cmap='plasma')

# --- CELL 35 ---
# Sample figsize in inches
fig, ax = plt.subplots(figsize=(20,10))
# PCA DataFrame Correlation
corr = df_comp.corr()
sns.heatmap(corr, cmap='YlGnBu', annot_kws={'size':30}, ax=ax)
ax.set_title("PCA Correlation Matrix", fontsize=14)
plt.show()

# --- CELL 36 ---
# plot a scree plot
plt.plot(np.cumsum(pca.explained_variance_ratio_))
plt.xlabel('Number of Features')
plt.ylabel('Explained Variance')

# --- CELL 38 ---
from sklearn.model_selection import train_test_split
X = x_pca
y = df['Label']

# --- CELL 39 ---
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=101)

# --- CELL 41 ---
from sklearn.linear_model import LogisticRegression
logmodel = LogisticRegression(max_iter=3000)

# --- CELL 42 ---
logmodel.fit(X_train, y_train)

# --- CELL 43 ---
predLR = logmodel.predict(X_test)

# --- CELL 44 ---
from sklearn.metrics import classification_report, confusion_matrix
print(classification_report(y_test, predLR))

# --- CELL 45 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predLR)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 47 ---
#KNN
from sklearn.neighbors import KNeighborsClassifier

# --- CELL 48 ---
knn = KNeighborsClassifier()

# --- CELL 49 ---
knn.fit(X_train, y_train)

# --- CELL 50 ---
predKNN = knn.predict(X_test)

# --- CELL 51 ---
print(classification_report(y_test, predKNN))

# --- CELL 52 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predKNN)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 54 ---
from sklearn.tree import DecisionTreeClassifier

# --- CELL 55 ---
dtree = DecisionTreeClassifier()

# --- CELL 56 ---
dtree.fit(X_train,y_train)

# --- CELL 57 ---
predDtree = dtree.predict(X_test)

# --- CELL 58 ---
from sklearn.metrics import classification_report, confusion_matrix

# --- CELL 59 ---
print(classification_report(y_test, predDtree))

# --- CELL 60 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predDtree)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 61 ---
from sklearn.ensemble import RandomForestClassifier

# --- CELL 62 ---
rfc = RandomForestClassifier()

# --- CELL 63 ---
rfc.fit(X_train, y_train)

# --- CELL 64 ---
predRFC = rfc.predict(X_test)

# --- CELL 65 ---
print(classification_report(y_test, predRFC))

# --- CELL 66 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predRFC)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 68 ---
from sklearn.naive_bayes import GaussianNB

# --- CELL 69 ---
# Build a Gaussian Classifier
nbgc = GaussianNB()

# --- CELL 70 ---
# Model training
nbgc.fit(X_train, y_train)

# Predict Output
predNBGC = nbgc.predict(X_test)

# --- CELL 71 ---
print(classification_report(y_test, predNBGC))

# --- CELL 72 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, predNBGC)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');

# --- CELL 74 ---
from sklearn.svm import SVC

# --- CELL 75 ---
svc = SVC()
'''
generalization:
low C = high bias, low variance
high C = low bias, low variance

low gamma = high variance
high gamma = low variance

gamma ada tergantung rbf
'''

# --- CELL 76 ---
svc.fit(X_train, y_train)

# --- CELL 77 ---
pred_svc = svc.predict(X_test)

# --- CELL 78 ---
print(classification_report(y_test, pred_svc))

# --- CELL 79 ---
# confusion matrix
group_names = ['True Pos', 'False Pos', 'False Neg', 'True Neg']
test_cnf_matrix = confusion_matrix(y_test, pred_svc)
test_counts = ["{0:0.0f}".format(value) for value in test_cnf_matrix.flatten()]
test_percentage = ["{0:.2%}".format(value) for value in test_cnf_matrix .flatten()/np.sum(test_cnf_matrix)]
test_labels = [f"{v1}\n{v2}\n{v3}" for v1, v2, v3 in zip(group_names,test_counts,test_percentage)]
test_labels = np.asarray(test_labels).reshape(2,2)
plt.figure(figsize = (16,5))
sns.heatmap(test_cnf_matrix, annot=test_labels, fmt='', cmap='viridis');
