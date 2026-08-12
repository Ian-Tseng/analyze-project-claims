def score(record):
    return record["prediction"]


def summarize(records):
    return [score(record) for record in records]
