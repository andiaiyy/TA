# --- CELL 0 ---
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

# --- CELL 1 ---
df = pd.read_csv('/content/drive/MyDrive/ALLFLOWMETER_HIKARI2021.csv')

# --- CELL 2 ---
df.head()

# --- CELL 3 ---
df.drop(['Unnamed: 0', 'Unnamed: 0.1'], axis = 1, inplace=True)

# --- CELL 4 ---
df.describe()

# --- CELL 5 ---
df_exclude_object = df.select_dtypes(exclude=['object'])

# --- CELL 6 ---
sns.heatmap(df_exclude_object.isnull(), yticklabels=False, cbar=False, cmap='viridis')

# --- CELL 7 ---
df_exclude_object.shape

# --- CELL 8 ---
X = df_exclude_object.iloc[:,:-1]
y = df_exclude_object.iloc[:,-1]

# --- CELL 9 ---
from sklearn.preprocessing import StandardScaler

# --- CELL 10 ---
#membuat feature matrix https://medium.com/data-science-365/principal-component-analysis-pca-with-scikit-learn-1e84a0c731b0
#https://towardsdatascience.com/using-principal-component-analysis-pca-for-machine-learning-b6e803f5bf1e
X_fea_mat = X.values
scaler = StandardScaler()
scaler.fit(X_fea_mat)
X_scaled = scaler.transform(X_fea_mat)

# --- CELL 11 ---
from sklearn.decomposition import PCA

# --- CELL 12 ---
pca_95 = PCA(n_components=0.95, random_state=2023)
pca_95.fit(X_scaled)
x_scaled_pca95 = pca_95.transform(X_scaled)


# --- CELL 13 ---
# print the explained variances
print("Variances (Percentage):")
print(pca_95.explained_variance_ratio_ * 100)
print()


# --- CELL 14 ---
# plot a scree plot
plt.plot(np.cumsum(pca_95.explained_variance_ratio_))
plt.xlabel('banyak komponen/feature')
plt.ylabel('Explained Variance')

# --- CELL 15 ---
x_scaled_pca95.shape

# --- CELL 16 ---
df_reducted = pd.DataFrame(x_scaled_pca95, columns = ['PC1', 'PC2', 'PC3', 'PC4', 'PC5',
                                                        'PC6', 'PC7', 'PC8', 'PC9', 'PC10',
                                                        'PC11', 'PC12', 'PC13', 'PC14', 'PC15',
                                                        'PC16', 'PC17', 'PC18', 'PC19', 'PC20',
                                                        'PC21', 'PC22', 'PC23', 'PC24', 'PC25',
                                                        'PC26', 'PC27'])

# --- CELL 17 ---
from sklearn.model_selection import train_test_split

# --- CELL 18 ---
X_train, X_test, y_train, y_test = train_test_split(df_reducted, y, test_size=0.3, random_state=101)

# --- CELL 19 ---
from sklearn.linear_model import LogisticRegression
logmodel = LogisticRegression(max_iter=3000)

# --- CELL 20 ---
logmodel.fit(X_train, y_train)

# --- CELL 21 ---
predictions = logmodel.predict(X_test)

# --- CELL 22 ---
from sklearn.metrics import classification_report
print(classification_report(y_test, predictions))

# --- CELL 23 ---
df.iloc[:,-1] #cuman target 'label'

# --- CELL 25 ---
df[['Label','traffic_category']]

# --- CELL 26 ---
df.groupby(by='Label').count()['traffic_category']

# --- CELL 27 ---
df[df['Label']==0]
