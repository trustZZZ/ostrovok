import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

from langchain_openai import ChatOpenAI

def test_llm():
    print("🔌 Проверка подключения к LLM...")
    
    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        openai_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        openai_api_base=os.getenv("LLM_BASE_URL"),
        temperature=0.1
    )
    
    try:
        # Простой тестовый запрос, имитирующий задачу агента
        response = llm.invoke("Кратко (в 1 предложении) объясни, почему отель с координатами 54.96, 20.48 подходит под запрос 'тихий вид на закат'.")
        print("✅ Успех! Ответ от LLM:")
        print("-" * 50)
        print(response.content)
        print("-" * 50)
    except Exception as e:
        print(f"❌ Ошибка подключения к LLM: {e}")
        print("Проверьте LLM_API_KEY и LLM_BASE_URL в файле .env")

if __name__ == "__main__":
    test_llm()