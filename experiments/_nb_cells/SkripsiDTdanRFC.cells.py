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
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3)

# --- CELL 8 ---
from sklearn.tree import DecisionTreeClassifier

# --- CELL 9 ---
dtree = DecisionTreeClassifier()

# --- CELL 10 ---
dtree.fit(X_train,y_train)

# --- CELL 11 ---
pred_dtc = dtree.predict(X_test)

# --- CELL 12 ---
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay

# --- CELL 13 ---
print(classification_report(y_test, pred_dtc))

# --- CELL 14 ---
labels = ["Benign", "Malicious"]
cm = confusion_matrix(y_test, pred_dtc)
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=labels)
disp.plot(cmap="viridis", values_format='');

# --- CELL 16 ---
from sklearn.ensemble import RandomForestClassifier

# --- CELL 17 ---
rfc = RandomForestClassifier()

# --- CELL 18 ---
rfc.fit(X_train, y_train)

# --- CELL 19 ---
pred_rfc = rfc.predict(X_test)

# --- CELL 20 ---
print(classification_report(y_test, pred_rfc))

# --- CELL 21 ---
labels = ["Benign", "Malicious"]
cm = confusion_matrix(y_test, pred_rfc)
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=labels)
disp.plot(cmap="viridis", values_format='');
