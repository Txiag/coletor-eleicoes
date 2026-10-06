RESULT_LEVELS = (("br", "brasil"), ("uf", "ufs"), ("mu", "municipios"), ("zona", "zonas"))


def result_levels(config):
    levels = {name: True for _, name in RESULT_LEVELS}
    configured = config.get("levels", {})
    if not isinstance(configured, dict) or configured.keys() - levels.keys():
        raise ValueError("results.levels aceita somente brasil, ufs, municipios e zonas")
    if any(not isinstance(value, bool) for value in configured.values()):
        raise ValueError("Os toggles de results.levels devem ser true ou false")
    return levels | configured


class ResultSchedule:
    def __init__(self, db, dataset):
        self.db = db
        self.dataset = dataset
        self.pass_key = dataset + "/results/pass"
        self.progress_prefix = dataset + "/results/completed/"

    def begin_pass(self):
        row = self.db.execute("SELECT value FROM collection_state WHERE key=?", (self.pass_key,)).fetchone()
        self.pass_number = int(row[0]) if row else 1
        self.completed = {row[0] for row in self.db.execute(
            "SELECT substr(key,?) FROM collection_state WHERE substr(key,1,?)=? AND value=?",
            (len(self.progress_prefix) + 1, len(self.progress_prefix), self.progress_prefix, self.pass_number))}
        self.completed.update(row[0] for row in self.db.execute(
            "SELECT source_url FROM results WHERE dataset=? AND completed=1", (self.dataset,)))

    def pending(self, targets, kind, municipalities_by_state):
        pending = [target for target in targets if target.kind == kind and target.url not in self.completed]
        if kind == "mu":
            return sorted(pending, key=lambda target: (
                len(municipalities_by_state[target.uf]), target.uf, target.municipality,
                target.election, target.office, target.url))
        if kind == "zona":
            votes = self._municipal_votes()
            return sorted(pending, key=lambda target: self._zone_priority(target, votes))
        return sorted(pending, key=lambda target: (target.uf, target.election, target.office, target.url))

    def complete(self, target):
        with self.db:
            self.db.execute("""INSERT INTO collection_state(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (self.progress_prefix + target.url, self.pass_number))
        self.completed.add(target.url)

    def finish_pass(self):
        with self.db:
            self.db.execute("""INSERT INTO collection_state(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (self.pass_key, self.pass_number + 1))

    def _municipal_votes(self):
        return {(row["election"], row["office"], row["uf"], row["municipality"]): row["votes"]
                for row in self.db.execute("""SELECT election,office,uf,municipality,votes
                    FROM results
                    WHERE dataset=? AND kind='mu' AND available=1 AND votes IS NOT NULL""", (self.dataset,))}

    @staticmethod
    def _zone_priority(target, municipal_votes):
        votes = municipal_votes.get((target.election, target.office, target.uf, target.municipality))
        # Um total desconhecido fica depois de zero votos, sem inventar uma estimativa.
        return (votes is None, -votes if votes is not None else 0,
                target.uf, target.municipality, target.election, target.office, target.area, target.url)
