from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class TelegramUser(Base):
    __tablename__ = "telegram_users"
    id = Column(Integer, primary_key=True)
    name = Column(String(30))
    role = Column(String(10))

    def __init__(self, id, name, role):
        self.id = id
        self.name = name
        self.role = role

    def __repr__(self):
        return "%id=s,role=%s,name=%s" % (self.id, self.role, self.name)
