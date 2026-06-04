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
#ingat KNN itu sangat susah dengan fitur yang banyak krn konsepnya itu mengecek titik terdekatnya

from sklearn.preprocessing import StandardScaler

# --- CELL 9 ---
scaler = StandardScaler()
scaler.fit(df_exclude_object.drop('Label', axis=1)) #jangan ambil target class yang kita mau predcit

# --- CELL 10 ---
scaled_features = scaler.transform(df_exclude_object.drop('Label', axis=1))

# --- CELL 11 ---
df_feat = pd.DataFrame(scaled_features, columns = df_exclude_object.columns[:-1]) #:-1 artinya kecuali yang terakhir

# --- CELL 12 ---
df_feat.head()

# --- CELL 13 ---
from sklearn.model_selection import train_test_split

# --- CELL 14 ---
X = df_feat #bisa ji juga scaled_features
y = df['Label']
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=101)

# --- CELL 15 ---
#KNN
from sklearn.neighbors import KNeighborsClassifier

# --- CELL 16 ---
knn = KNeighborsClassifier(n_neighbors=2)

# --- CELL 17 ---
knn.fit(X_train, y_train)

# --- CELL 18 ---
pred = knn.predict(X_test)

# --- CELL 19 ---
pred

# --- CELL 20 ---
from sklearn.metrics import classification_report, confusion_matrix

# --- CELL 21 ---
#Original imbalance, KNN n=2
print(classification_report(y_test, pred))

# --- CELL 22 ---
#Original imbalance, KNN n=1
print(classification_report(y_test, pred))

# --- CELL 23 ---
print(confusion_matrix(y_test, pred))

# --- CELL 25 ---
y.value_counts().plot.pie(autopct='%.2f')

# --- CELL 26 ---
from imblearn.under_sampling import RandomUnderSampler

# --- CELL 27 ---
rus = RandomUnderSampler(sampling_strategy=1)
X_res, y_res = rus.fit_resample(X_train, y_train)
ax = y_res.value_counts().plot.pie(autopct='%.2f')
ax.set_title('Under Sampling')

# --- CELL 28 ---
y_res.value_counts()

# --- CELL 29 ---
knn = KNeighborsClassifier(n_neighbors=1)

# --- CELL 30 ---
knn.fit(X_res, y_res)

# --- CELL 31 ---
pred = knn.predict(X_test)

# --- CELL 32 ---
pred

# --- CELL 33 ---
#Undersampling, KNN n=2
print(classification_report(y_test, pred))

# --- CELL 35 ---
#Undersampling, KNN n=1
print(classification_report(y_test, pred))

# --- CELL 36 ---
print(confusion_matrix(y_test, pred))

# --- CELL 38 ---
error_rate=[]

for i in range(1, 10):
  knn = KNeighborsClassifier(n_neighbors=i)
  knn.fit(X_res, y_res)
  pred_i = knn.predict(X_test)
  error_rate.append(np.mean(pred_i != y_test))


# --- CELL 39 ---
plt.figure(figsize = (10,6))
plt.plot(range(1,10), error_rate, color = 'blue', linestyle = '--', marker = 'o', markerfacecolor = 'red', markersize = 10)
plt.title('Error Rate vs K Value')
plt.xlabel('K')
plt.ylabel('Error Rate')
