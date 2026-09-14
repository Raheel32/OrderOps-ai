from langgraph.checkpoint.postgres import PostgresSaver
from app.config import settings

if __name__ == "__main__":
    with PostgresSaver.from_conn_string(settings.checkpoint_db_url) as saver:
        saver.setup()
    print("LangGraph checkpoint tables ready.")
