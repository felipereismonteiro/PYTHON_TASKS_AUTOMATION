from dotenv import load_dotenv
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import requests
from datetime import timezone
from datetime import datetime

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
CHAT_API_KEY = os.getenv("CHAT_API_KEY")
PASSWORD_GMAIL = os.getenv("PASSWORD_GMAIL")
PUSH_BULLET_API_KEY = os.getenv("PUSH_BULLET_API_KEY")
DATABASE_ID = os.getenv("DATABASE_ID")

required = {
    "NOTION_TOKEN": NOTION_TOKEN,
    "CHAT_API_KEY": CHAT_API_KEY,
    "PASSWORD_GMAIL": PASSWORD_GMAIL,
    "PUSH_BULLET_API_KEY": PUSH_BULLET_API_KEY,
    "DATABASE_ID": DATABASE_ID
}

missing = [name for name, value in required.items() if not value]
if missing:
    print("⚠️ Variáveis ausentes:", ", ".join(missing))
else:
    print("✅ Todas as variáveis de ambiente foram carregadas corretamente.")

headers_notion = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}


def send_pushbullet_notification(title: str, body: str):
    """
    Envia uma notificação via Pushbullet.
    """
    url = "https://api.pushbullet.com/v2/pushes"
    headers = {
        "Access-Token": PUSH_BULLET_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "type": "note",
        "title": title,
        "body": body
    }

    res = requests.post(url, headers=headers, json=data)
    if res.status_code == 200:
        print("📲 Notificação enviada com sucesso!")
    else:
        print("❌ Erro ao enviar notificação:", res.status_code, res.text)


def send_plan_email(subject, html_body, sender_email, receiver_email, smtp_server, smtp_port, password):
    """
    Envia e-mail com corpo HTML (com fallback simples em texto).
    """
    msg = MIMEMultipart("alternative")
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject

    # Fallback simples em texto (remove tags grosseiramente)
    plain_fallback = ("Plano do Dia (versão texto)\n\n"
                      + html_body.replace("<br>", "\n").replace("<br/>", "\n")
                      .replace("</li>", "\n").replace("</p>", "\n")
                      .replace("<strong>", "").replace("</strong>", "")
                      .replace("&amp;", "&"))

    msg.attach(MIMEText(plain_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, password)
            server.send_message(msg)
        print("✅ E-mail enviado com sucesso!")
    except Exception as e:
        print("❌ Erro ao enviar e-mail:", e)


def format_tasks(tasks_json):
    """
    Recebe a lista bruta de tasks vinda da API do Notion e retorna uma string formatada.
    Cada tarefa vem com nome e descrição em linhas separadas.
    """
    # se veio como string JSON, converte pra lista
    if isinstance(tasks_json, str):
        tasks = json.loads(tasks_json)
    else:
        tasks = tasks_json

    lines = []
    for task in tasks:
        props = task.get("properties", {})
        title_data = props.get("🐈 Sistema", {}).get("title", [])
        description_data = props.get("🍀 Descrição", {}).get("rich_text", [])

        # extrai texto do título
        title = "".join(t.get("plain_text", "") for t in title_data).strip()
        # extrai texto da descrição (se tiver)
        description = "".join(d.get("plain_text", "") for d in description_data).strip()

        if title:
            lines.append(f"🟢 {title}")
            if description:
                lines.append(f"   ↳ {description}")
            lines.append("")  # linha em branco entre tarefas

    return "\n".join(lines)

def ask_chatgpt_plan(tasks_text, model="gpt-4o-mini"):
    prompt = f"""
    Você é um assistente pessoal que cria um plano diário completo e equilibrado, sempre em formato de **tópicos curtos e práticos**.

    Essas são minhas tarefas e descrições:
    {tasks_text}

    Monte um plano do dia **abrangendo todas as dimensões**:
    1. Mental e emocional (clareza, leitura, respiração, reflexão)
    2. Social e interpessoal (expressão, escuta, exposições, Erika)
    3. Estilo e imagem (looks, ajustes, fotos, compras)
    4. Energia física (treino, sono, hidratação, aparência)

    Instruções:
    - Tarefas com “(Diáriamente)” sempre aparecem.
    - “(Semanalmente)” podem ser adaptadas como pequenas ações de preparo.
    - Use **apenas tópicos** com emojis e frases diretas.
    - Divida em seções: ☀️ Manhã, 🌤️ Tarde, 🌙 Noite.
    - Cada tópico deve descrever **o que fazer** em 1 linha, explicando como fazer cada topico com base no que está no notion.
    - Finalize com uma frase de incentivo curta e positiva.
    - Não use texto corrido nem blocos, apenas listas com marcadores.

    Formato de saída desejado:
    ☀️ **Manhã**
    - ...
    
    - ...

    🌤️ **Tarde**
    - ...
    
    - ...

    🌙 **Noite**
    - ...
    
    - ...

    💬 Frase final: ...
    
    """

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {CHAT_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Você é um assistente pessoal organizado e direto."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.6
    }

    res = requests.post(url, headers=headers, json=body)
    if res.status_code != 200:
        print("Erro ao consultar ChatGPT:", res.status_code, res.text)
        return None

    return res.json()["choices"][0]["message"]["content"]

def get_tasks(database_id, filters=None, page_size=100, headers=None):
    """
    Retorna todas as tasks da database do Notion aplicando o filtro fornecido.
    Faz paginação automática até trazer todas as páginas.
    """
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    all_results = []
    payload = {"page_size": page_size}

    if filters:
        payload["filter"] = filters

    headers_to_use = headers or {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    has_more = True
    next_cursor = None

    while has_more:
        if next_cursor:
            payload["start_cursor"] = next_cursor

        print(f"Consultando Notion com payload: {payload}")  # debug opcional

        response = requests.post(url, headers=headers_to_use, json=payload)
        if response.status_code != 200:
            print("Erro ao consultar Notion:", response.status_code, response.text)
            break

        data = response.json()
        all_results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    print(f"Total de tasks encontradas: {len(all_results)}")
    return all_results


today = datetime.now(timezone.utc).date().isoformat()
filters = {
    "and": [
        {
            "property": "✅ Status",
            "checkbox": {"equals": False}
        },
        {
            "property": "📅 Deadline",
            "date": {"equals": today}
        }
    ]
}

tasks = get_tasks(DATABASE_ID, filters)

plan = ask_chatgpt_plan(format_tasks(tasks), model="gpt-4o-mini")

# send_plan_email(
#     subject="Plano do Dia 🌞",
#     html_body=gerar_html_plano_do_dia(conteudo_md=plan),
#     sender_email="felipe.dreis.monteiro@gmail.com",
#     receiver_email="felipe.dreis.monteiro@gmail.com",
#     smtp_server="smtp.gmail.com",
#     smtp_port=587,
#     password=PASSWORD_GMAIL
# )

send_pushbullet_notification(
    title="Plano do Dia Enviado!",
    body=plan)



