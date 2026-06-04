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
y = df_exclude_object.iloc[:,-1]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

# --- CELL 9 ---
from sklearn.svm import SVC

# --- CELL 10 ---
svc = SVC()
'''
generalization:
low C = high bias, low variance
high C = low bias, low variance

low gamma = high variance
high gamma = low variance

gamma ada tergantung rbf
'''

# --- CELL 11 ---
svc.fit(X_train, y_train)

# --- CELL 12 ---
pred_svc = svc.predict(X_test)

# --- CELL 13 ---
from sklearn.metrics import classification_report, confusion_matrix

# --- CELL 14 ---
print(confusion_matrix(y_test, pred_svc))
print('\n')
print(classification_report(y_test, pred_svc))

# --- CELL 17 ---
from sklearn.model_selection import GridSearchCV

# --- CELL 18 ---
param_grid = {
    'C':[0.1, 10, 100, 1000],
    'gamma': [1, 0.1, 0.01, 0.001, 0.0001]

}

# --- CELL 19 ---
grid = GridSearchCV(estimator = SVC(), param_grid = param_grid, verbose = 3 )

# --- CELL 20 ---
grid.fit(X_train, y_train)

# --- CELL 21 ---
grid.best_params_

# --- CELL 22 ---
grid.best_estimator_

# --- CELL 23 ---
grid_predictions = grid.predict(X_test)

# --- CELL 24 ---
print(confusion_matrix(y_test, grid_predictions))
print('\n')
print(classification_report(y_test, grid_predictions))
