import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import accuracy_score

df = pd.read_csv('base_conhecimento.csv', sep=';')

df['Causa da morte'] = df['Causa da morte'].str.strip()

le = LabelEncoder()
df['Classificação'] = le.fit_transform(df['Classificação'])

X = df['Causa da morte']
y = df['Classificação']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

vectorizer = TfidfVectorizer()
X_train_vec = vectorizer.fit_transform(X_train)
X_test_vec = vectorizer.transform(X_test)

model = MultinomialNB()
model.fit(X_train_vec, y_train)

y_pred = model.predict(X_test_vec)
accuracy = accuracy_score(y_test, y_pred)
print(f'Acurácia: {accuracy:.2f}')

novas_causas = ["TRAUMATISMO CRANIO FALICO", "anemia", "diabetes"]
novas_causas_vec = vectorizer.transform(novas_causas)
predicoes = model.predict(novas_causas_vec)

classificacoes = le.inverse_transform(predicoes)

probabilidades = model.predict_proba(novas_causas_vec)

for causa, classificacao, probabilidade in zip(novas_causas, classificacoes, probabilidades):
    probabilidade_classificacao = probabilidade[le.transform([classificacao])[0]] * 100
    print(f'Causa: {causa} - Classificação: {classificacao} - Acurácia: {probabilidade_classificacao:.2f}%')
