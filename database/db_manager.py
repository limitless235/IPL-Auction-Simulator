import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base, AuctionSession, StateSnapshot
from engine.state import AuctionState

class DatabaseManager:
    def __init__(self):
        # Default to SQLite for local dev if DATABASE_URL is missing
        self.db_url = os.getenv("DATABASE_URL", "sqlite:///./auction_local.db")
        # Render/Postgres often requires 'postgresql://' instead of 'postgres://'
        if self.db_url.startswith("postgres://"):
            self.db_url = self.db_url.replace("postgres://", "postgresql://", 1)
            
        self.engine = create_engine(self.db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
    def init_db(self):
        """Create tables if they don't exist."""
        Base.metadata.create_all(bind=self.engine)

    def save_state(self, session_name: str, state: AuctionState):
        """Saves a snapshot of the current AuctionState to the DB."""
        db = self.SessionLocal()
        try:
            # 1. Ensure session exists
            session = db.query(AuctionSession).filter(AuctionSession.session_name == session_name).first()
            if not session:
                session = AuctionSession(session_name=session_name)
                db.add(session)
                db.commit()
                db.refresh(session)
            
            # 2. Add snapshot (convert pydantic model to dict/json)
            state_data = state.model_dump() if hasattr(state, 'model_dump') else state.dict()
            snapshot = StateSnapshot(
                session_id=session.id,
                state_json=state_data
            )
            db.add(snapshot)
            db.commit()
            return True
        except Exception as e:
            print(f"Database Save Error: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def get_latest_state(self, session_name: str):
        """Retrieves the most recent snapshot for a given session."""
        db = self.SessionLocal()
        try:
            session = db.query(AuctionSession).filter(AuctionSession.session_name == session_name).first()
            if not session:
                return None
            
            latest_snapshot = db.query(StateSnapshot)\
                .filter(StateSnapshot.session_id == session.id)\
                .order_by(StateSnapshot.timestamp.desc())\
                .first()
            
            return latest_snapshot.state_json if latest_snapshot else None
        finally:
            db.close()
