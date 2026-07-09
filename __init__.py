from . import AISlicingAssistant


def getMetaData():
    return {}


def register(app):
    return {"extension": AISlicingAssistant.AISlicingAssistant()}
