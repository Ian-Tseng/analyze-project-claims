from runner import score, summarize


def replay(records):
    return summarize(records), [score(record) for record in records]
