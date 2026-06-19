import os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings, AzureChatOpenAI
import psycopg2

load_dotenv()

openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
openai_api_base = "https://idpIA.openai.azure.com/"
openai_api_version = "2023-03-15-preview"
embedding_model = "gpt-4o-mini"

embeddings = OpenAIEmbeddings(
    openai_api_key=openai_api_key,
    openai_api_base=openai_api_base,
    openai_api_version=openai_api_version,
    deployment=embedding_model
)

conn = psycopg2.connect(
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT")
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS vetores_azure (
    id SERIAL PRIMARY KEY,
    cod_cuenta VARCHAR(255),
    saldo NUMERIC,
    num_portabilidade VARCHAR(255),
    nome VARCHAR(255),
    cpf VARCHAR(11),
    cedente_nome VARCHAR(255),
    cedente_cnpj_fundo VARCHAR(255),
    cedente_proc_susep VARCHAR(255),
    cession_nome VARCHAR(255),
    cession_cnpj_fundo VARCHAR(255),
    cession_proc_susep VARCHAR(255),
    vetor FLOAT8[]  -- Usando um array de floats para armazenar os vetores
);
""")
conn.commit()

cursor.execute("""
SELECT cod_cuenta, saldo, num_portabilidade, nome, cpf, cedente_nome,
       cedente_cnpj_fundo, cedente_proc_susep, cession_nome,
       cession_cnpj_fundo, cession_proc_susep
FROM solicitacoes  -- Certifique-se de substituir com o nome correto da sua tabela
""")

registros = cursor.fetchall()

for dado in registros:
    cod_cuenta, saldo, num_portabilidade, nome, cpf, cedente_nome, cedente_cnpj_fundo, cedente_proc_susep, cession_nome, cession_cnpj_fundo, cession_proc_susep = dado

    vetor = embeddings.invoke(nome)

    if vetor is not None:
        insert_query = """
        INSERT INTO vetores_azure (cod_cuenta, saldo, num_portabilidade, nome, cpf, cedente_nome, cedente_cnpj_fundo, cedente_proc_susep, cession_nome, cession_cnpj_fundo, cession_proc_susep, vetor)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (
            cod_cuenta, saldo, num_portabilidade, nome, cpf, cedente_nome,
            cedente_cnpj_fundo, cedente_proc_susep, cession_nome,
            cession_cnpj_fundo, cession_proc_susep, vetor
        ))

conn.commit()

cursor.close()
conn.close()

print("Dados inseridos na tabela vet")
