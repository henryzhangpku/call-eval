"""Synthetic contact-centre calls for a loan-servicing desk. Everything here is synthetic.

Deterministic for a given seed. For each call the generator first draws a LATENT
truth per intent (resolved yes/partial/no, effort signals, expressed feeling),
derives the true satisfaction (1-5) and sentiment (happy/mild/not_happy), and only
then writes the transcript from that truth. The system under test sees the
transcript; the latent truth goes to a separate answer key.

Outputs (under data/):
    calls.jsonl                 transcripts: what the pipeline sees
    surveys.csv                 noisy post-call survey scores, about a third of calls,
                                with response bias (unhappy callers answer more)
    golden/dev.csv              200 calls labelled by two simulated annotators
    golden/holdout_sealed.csv   100 more, sealed: read only by `calleval holdout`
    golden/splits.json          which call ids are dev and which are holdout (ids only, no labels)
    _answer_key/truth.jsonl     the latent truth. Diagnostics only, never used to fit
"""

from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path

from calleval import paths

SEED = 20260914
N_CALLS = 400
N_GOLDEN = 300
N_DEV = 200
DAYS = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19", "2026-09-20"]

AGENT_NAMES = ["Alex", "Jordan", "Sam", "Riley", "Morgan", "Casey", "Taylor", "Jamie", "Drew", "Avery", "Quinn", "Reese"]
CALLER_NAMES = ["Maria", "James", "Priya", "Daniel", "Aisha", "Tom", "Wei", "Grace", "Luis", "Hannah", "Omar",
                "Ruth", "Kevin", "Sofia", "Marcus", "Elena", "Noah", "Fatima", "Ivan", "Chloe"]

# difficulty: how hard the intent is to resolve on one call; dept: where a transfer goes
INTENT_SPEC = {
    "balance": {"difficulty": 0.05, "dept": "account services", "topic": "your balance"},
    "payment": {"difficulty": 0.15, "dept": "payments", "topic": "a payment"},
    "escrow": {"difficulty": 0.40, "dept": "escrow", "topic": "your escrow account"},
    "payoff": {"difficulty": 0.30, "dept": "payoff", "topic": "a payoff quote"},
    "hardship": {"difficulty": 0.60, "dept": "loss mitigation", "topic": "hardship options"},
    "dispute": {"difficulty": 0.55, "dept": "research", "topic": "a dispute"},
    "late_fee": {"difficulty": 0.45, "dept": "fee review", "topic": "a late fee"},
}

ASK = {
    "balance": ["What is my current balance?", "How much do I still owe on the loan?",
                "Can you tell me what my principal balance is?", "I just want to check how much is left on my mortgage."],
    "payment": ["I need to make my payment for this month.", "I want to pay my mortgage today.",
                "Can I make a payment over the phone?", "I'm trying to pay but the website keeps erroring out."],
    "escrow": ["Why did my escrow payment go up?", "My monthly payment went up, is that the escrow?",
               "I got an escrow shortage letter and I don't understand it."],
    "payoff": ["I'm selling the house and need a payoff quote.", "Can I get a payoff statement?",
               "I need the payoff amount for my refinance."],
    "hardship": ["I lost my job and I'm going to have trouble paying.",
                 "Do you have any hardship programs? Money is tight right now.", "I need to talk about forbearance."],
    "dispute": ["There's a charge on my statement I don't recognize.",
                "You reported me late to the credit bureau and I wasn't late.",
                "I want to dispute the property inspection fee."],
    "late_fee": ["I was charged a late fee but I paid on time.", "Why is there a late fee on my account?",
                 "I want that late fee removed, my payment was on the fifteenth."],
}

SHORT = {
    "balance": "I need my current balance.", "payment": "I want to make a payment.",
    "escrow": "I'm asking why my escrow went up.", "payoff": "I need a payoff quote.",
    "hardship": "I need help with a hardship plan.", "dispute": "I'm disputing that charge.",
    "late_fee": "I want the late fee taken off.",
}

OUTCOME = {
    "balance": {
        "yes": ["Your unpaid principal balance is ${bal}.",
                "You currently owe ${bal} in principal, and your next payment is due on the first.",
                "It's showing ${bal} remaining as of today."],
        "partial": ["I can see the principal, ${bal}, but the interest breakdown isn't loading. I'll email it to you.",
                    "The balance is about ${bal}, but I can't give you an exact figure until tonight's posting."],
        "no": ["I'm not able to see the balance right now, our system is slow. Can you try again later?",
               "The account is locked for review, so I can't read out the balance on this call."],
    },
    "payment": {
        "yes": ["Your payment of ${amt} is scheduled for today. Confirmation number {conf}.",
                "Done. ${amt} will post today, confirmation {conf}.",
                "That went through, you're all set for this month."],
        "partial": ["I've taken the payment, but it won't post until Monday, so a late flag may show for a few days.",
                    "I can take ${small} today, the rest will need to come from another account."],
        "no": ["I'm sorry, the bank account on file was declined. I can't take the payment right now.",
               "The system won't accept a payment after the cutoff today."],
    },
    "escrow": {
        "yes": ["Your property tax went up by ${amt} this year, so the escrow portion increased. I've spread the shortage over twelve months.",
                "The shortage is ${amt} because the insurance premium rose. It's now spread over twelve months, so your payment rises by about ${small}."],
        "partial": ["I've requested a new escrow analysis. It takes about ten business days, and the payment may change after that.",
                    "I can see the tax went up, but I can't adjust the shortage until the analysis team reviews it."],
        "no": ["I don't have the escrow analysis in front of me, and I'm not able to change anything on it.",
               "That's set by the escrow department, there's nothing I can do from here."],
    },
    "payoff": {
        "yes": ["The payoff statement good through the end of the month is on its way to your email. The amount is ${bal}.",
                "I've sent the payoff quote to your email, it's ${bal} good through the thirtieth."],
        "partial": ["I've requested the payoff quote. It can take up to five business days to arrive.",
                    "I can give you an estimate of ${bal}, but the official statement has to be ordered separately."],
        "no": ["Payoff quotes have to be requested by the title company, not by you.",
               "I can't release a payoff figure until the authorization form is on file."],
    },
    "hardship": {
        "yes": ["We can place the loan in a three-month forbearance. I'll send the agreement today, and nothing is reported late while it's active.",
                "You qualify for our hardship program. I've opened the application and approved the first three months."],
        "partial": ["I've opened a hardship application. The loss mitigation team will review it within ten days.",
                    "I can pause the late fees this month, but the forbearance itself needs a review."],
        "no": ["I can't set up forbearance on this call. You'd need to send a written request to loss mitigation.",
               "Unfortunately you don't qualify for any of our programs right now."],
    },
    "dispute": {
        "yes": ["I see the error. I've removed the charge and you'll see the credit on your next statement.",
                "You're right, I've sent a correction to the credit bureaus today."],
        "partial": ["I've opened a dispute ticket. Research takes up to thirty days.",
                    "I've escalated it to the research team, they'll decide on the correction."],
        "no": ["That charge is valid according to the account notes, so I can't remove it.",
               "We're not able to change what was reported to the bureaus."],
    },
    "late_fee": {
        "yes": ["I can see the payment arrived within the grace period. I've reversed the ${fee} late fee.",
                "You're right, that fee was applied in error. It's been removed."],
        "partial": ["I can waive half of the fee as a courtesy, so ${halffee} instead of ${fee}.",
                    "I've submitted a fee reversal request, it needs supervisor approval."],
        "no": ["The payment posted after the grace period, so the ${fee} fee stands.",
               "I'm not authorized to waive the fee. It stays on the account."],
    },
}

# An agent claiming resolution that did not happen; the caller contests it.
GAMING_CLAIM = ["Okay, that's all taken care of for you.", "Great, so that's sorted. Is there anything else?"]
GAMING_CONTEST = ["Wait, nothing actually changed though.", "Hold on, you haven't actually fixed anything.",
                  "That doesn't answer my question at all."]
GAMING_FOLLOW = ["I'm sorry, that's as far as I can take it today."]

REACT = {
    "happy": ["Oh great, thank you so much.", "That's a relief, really, thank you.",
              "Perfect, you've been really helpful.", "Wonderful, that was easy."],
    "mild": ["Okay.", "Alright, I guess that works.", "Fine.", "Okay, thanks.", "Got it."],
    "mild_polite_unresolved": ["Okay, I understand, thanks for trying.", "No problem, I appreciate you looking into it.",
                               "Alright. Thank you anyway, I know it's not your fault."],
    "unhappy": ["This is ridiculous.", "Honestly, I'm really frustrated.", "That's not acceptable.",
                "I've wasted my whole morning on this.", "I'm pretty upset about this, to be honest."],
}
CLOSE = {
    "happy": ["No, that's everything. Thanks so much for your help today!", "No, you've made my day, thank you."],
    "mild": ["No, that's it.", "That's all, thanks.", "No, that's everything."],
    "unhappy": ["No. I just hope someone actually fixes this.", "No. I'll be filing a complaint.",
                "No. Honestly this whole thing has been a mess."],
}
MISHEAR = ["Sorry, could you repeat that?", "I'm sorry, you're breaking up a little. What was that?",
           "Just to make sure, are you asking about your {other}?", "Let me make sure I understand. Can you say that again?"]
REPEAT = {
    "polite": ["Sorry, as I mentioned, {short}", "No worries. {short}"],
    "neutral": ["Like I said, {short}", "Again, {short}"],
    "irritable": ["I already told you. {short}", "I've said this twice now. {short}"],
}
HOLD = [("Let me place you on a brief hold while I look into that.", "Thank you for holding."),
        ("Can you hold for a moment? I need to check with my supervisor.", "Thanks for your patience, I'm back.")]
TRANSFER = ["I'm going to transfer you to our {dept} team.", "Let me connect you with {dept}, one moment please."]
TRANSFER_PICKUP = "Hi, this is {name} in {dept}. I understand you're calling about {topic}."
CALLBACK = ["Someone from {dept} will call you back within three business days.",
            "You'll need to call back tomorrow once the system is updated.",
            "We'll reach out by phone once the review is done."]

# ASR substitutions applied in "noisy audio" calls
ASR_SUBS = {
    "escrow": ["S grow", "ask row"], "payoff": ["pay off", "paid off"], "forbearance": ["for bearings", "four bearance"],
    "late fee": ["lay fee", "late feet"], "balance": ["ballots", "bounce"], "dispute": ["this pewt", "dis spute"],
    "hardship": ["hard ship", "heart ship"], "principal": ["principle"], "statement": ["state mint"],
}


def _money(rng, lo, hi):
    return f"{rng.randint(lo, hi):,}"


def _fill(rng, s, intent, other):
    fee = rng.choice([35, 45, 50, 75])
    return s.format(
        bal=_money(rng, 80_000, 420_000) + f".{rng.randint(10, 99)}", amt=_money(rng, 900, 3_200),
        small=_money(rng, 40, 260), conf=f"{rng.randint(100000, 999999)}", fee=fee, halffee=fee // 2,
        other=other.replace("_", " "),
    )


def draw_resolution(rng, skill, difficulty):
    s = skill - difficulty + rng.gauss(0, 0.35)
    return "yes" if s > 0.10 else ("partial" if s > -0.18 else "no")


def draw_valence(rng, temperament, resolved, effort):
    r = rng.random()
    if temperament == "polite":
        if resolved == "yes":
            return "happy" if r < 0.70 else "mild"
        return "unhappy" if (resolved == "no" and r < 0.08) else ("happy" if (resolved == "partial" and r > 0.85) else "mild")
    if temperament == "neutral":
        if resolved == "yes":
            return "happy" if (r < 0.55 and effort < 2) else ("unhappy" if r > 0.95 else "mild")
        if resolved == "partial":
            return "unhappy" if r < 0.25 + 0.1 * min(effort, 3) else ("happy" if r > 0.92 else "mild")
        return "unhappy" if r < 0.55 + 0.1 * min(effort, 3) else "mild"
    # irritable
    if resolved == "yes":
        if effort >= 2:
            return "unhappy" if r < 0.5 else "mild"
        return "happy" if r < 0.25 else ("unhappy" if r > 0.85 else "mild")
    if resolved == "partial":
        return "unhappy" if r < 0.65 else "mild"
    return "unhappy" if r < 0.92 else "mild"


def intent_satisfaction(rng, it, temperament):
    base = {"yes": 5.0, "partial": 3.4, "no": 1.9}[it["resolved"]]
    pen = 0.45 * it["repeats"] + 0.7 * it["transfers"] + 0.35 * it["holds"] + 0.5 * it["callback"]
    temp = {"polite": 0.2, "neutral": 0.0, "irritable": -0.3}[temperament]
    return base - pen + temp + rng.gauss(0, 0.35)


def call_truth(intents, closing, sat_values, dropped):
    """True CSAT (1-5) and sentiment from latent per-intent values."""
    worst, mean = min(sat_values), sum(sat_values) / len(sat_values)
    csat = int(min(5, max(1, round(0.65 * worst + 0.35 * mean - (0.5 if dropped else 0)))))
    vals = [it["valence"] for it in intents] + ([closing] if closing else [])
    if "unhappy" in vals and closing != "happy":
        sentiment = "not_happy"
    elif closing == "happy" or (vals.count("happy") * 2 >= len(vals) and "unhappy" not in vals):
        sentiment = "happy"
    else:
        sentiment = "mild"
    return csat, sentiment


class _Writer:
    """Accumulates turns with plausible timestamps."""

    def __init__(self, rng):
        self.rng, self.t, self.turns = rng, 0.0, []

    def say(self, speaker, text, gap=None):
        self.turns.append({"speaker": speaker, "t": round(self.t, 1), "text": text, "conf": 0.0})
        self.t += (gap if gap is not None else 1.5 + len(text) / 14.0 + self.rng.random() * 2.0)


def build_call(rng, call_id, agent, day):
    """Draw latent truth for one call, then write its transcript."""
    n_int = rng.choices([1, 2, 3], weights=[55, 35, 10])[0]
    intents = rng.sample(list(INTENT_SPEC), n_int)
    temperament = rng.choices(["polite", "neutral", "irritable"], weights=[35, 40, 25])[0]
    caller = rng.choice(CALLER_NAMES)
    dropped = rng.random() < 0.04
    w = _Writer(rng)
    w.say("agent", f"Thank you for calling loan servicing, this is {agent['name']}. Who am I speaking with?")
    w.say("caller", f"Hi, this is {caller}.")
    w.say("agent", "Thanks. Can you verify the last four of your social and the property address?")
    w.say("caller", f"Sure, it's {rng.randint(1000, 9999)}, and the address is on file.")
    w.say("agent", "Thank you, you're verified. How can I help today?")

    latent, sat_values = [], []
    for k, intent in enumerate(intents):
        spec = INTENT_SPEC[intent]
        skill = agent["skill"]
        resolved = draw_resolution(rng, skill, spec["difficulty"])
        repeats = min(3, _poisson(rng, (1.0 - skill) * 0.9))
        holds = min(2, _poisson(rng, 0.25 + spec["difficulty"] * 0.6))
        transfers = 0
        if rng.random() < spec["difficulty"] * 0.40:
            transfers = 2 if rng.random() < 0.2 else 1
        p_cb = {"yes": 0.03, "partial": 0.6, "no": 0.35}[resolved]
        callback = rng.random() < p_cb
        gaming = resolved == "no" and rng.random() < agent["gaming"]
        is_last = k == len(intents) - 1
        drop_here = dropped and is_last
        if drop_here:
            resolved, callback, gaming = "no", False, False
        effort = repeats + 1.5 * transfers + 0.5 * holds + callback
        valence = draw_valence(rng, temperament, resolved, effort)
        it = {"intent": intent, "resolved": resolved, "repeats": repeats, "transfers": transfers, "holds": holds,
              "callback": callback, "valence": valence, "gaming": gaming, "start_turn": len(w.turns)}

        # the ask, and any repeats
        prefix = "" if k == 0 else rng.choice(["Also, ", "One more thing. ", "And while I have you, "])
        ask = rng.choice(ASK[intent])
        lowered = ask if ask.startswith(("I ", "I'")) else ask[0].lower() + ask[1:]
        w.say("caller", prefix + lowered if prefix else ask)
        other = rng.choice([i for i in INTENT_SPEC if i != intent])
        for _ in range(repeats):
            w.say("agent", _fill(rng, rng.choice(MISHEAR), intent, other))
            w.say("caller", rng.choice(REPEAT[temperament]).format(short=SHORT[intent]))
        if drop_here:
            if holds:
                w.say("agent", HOLD[0][0])
            cut = rng.choice(["Okay, so what I'm seeing here is that the", "Let me just pull up the", "Right, so the"])
            w.say("agent", cut + " ...", gap=0.5)
            it["valence"] = "mild"
            it["end_turn"] = len(w.turns) - 1
            latent.append(it)
            sat_values.append(intent_satisfaction(rng, it, temperament))
            break
        for _ in range(holds):
            a, b = rng.choice(HOLD)
            w.say("agent", a)
            w.say("caller", rng.choice(["Sure.", "Okay.", "Fine."]))
            w.say("agent", b, gap=30 + rng.random() * 120)
        for j in range(transfers):
            w.say("agent", rng.choice(TRANSFER).format(dept=spec["dept"]))
            w.say("caller", rng.choice(["Okay.", "Again?", "Fine."]) if j else "Okay.")
            name2 = rng.choice([n for n in AGENT_NAMES if n != agent["name"]])
            w.say("agent", TRANSFER_PICKUP.format(name=name2, dept=spec["dept"], topic=spec["topic"]), gap=40 + rng.random() * 90)
            if rng.random() < 0.5:
                w.say("caller", "Yes. " + SHORT[intent])
        if gaming:
            w.say("agent", rng.choice(GAMING_CLAIM))
            w.say("caller", rng.choice(GAMING_CONTEST))
            w.say("agent", rng.choice(GAMING_FOLLOW))
        else:
            w.say("agent", _fill(rng, rng.choice(OUTCOME[intent][resolved]), intent, other))
        if callback:
            w.say("agent", rng.choice(CALLBACK).format(dept=spec["dept"]))
        if valence == "mild" and resolved != "yes" and temperament == "polite" and rng.random() < 0.6:
            w.say("caller", rng.choice(REACT["mild_polite_unresolved"]))
        else:
            w.say("caller", rng.choice(REACT[valence]))
        it["end_turn"] = len(w.turns) - 1
        latent.append(it)
        sat_values.append(intent_satisfaction(rng, it, temperament))

    closing = None
    if not dropped:
        worst = "unhappy" if any(i["valence"] == "unhappy" for i in latent) else latent[-1]["valence"]
        closing = worst if rng.random() < 0.75 else rng.choice(["happy", "mild", "unhappy"])
        if temperament == "polite" and closing == "unhappy":
            closing = "mild"
        w.say("agent", "Is there anything else I can help you with today?")
        w.say("caller", rng.choice(CLOSE[closing]))
        w.say("agent", "Thank you for calling, have a good day.")

    csat, sentiment = call_truth(latent, closing, sat_values, dropped)
    truth = {"call_id": call_id, "csat": csat, "sentiment": sentiment, "temperament": temperament,
             "dropped": dropped, "intents": latent, "closing_valence": closing,
             "sat_raw": [round(s, 3) for s in sat_values]}
    call = {"call_id": call_id, "date": day, "agent_id": agent["id"], "turns": w.turns,
            "duration_s": int(w.t + 3)}
    return call, truth


def _poisson(rng, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def add_mess(rng, call, truth):
    """ASR noise, lost speaker labels, cross-talk, garbled audio. Records what was done in truth['mess']."""
    mess = []
    turns = call["turns"]
    garbled = rng.random() < 0.04
    for t in turns:
        t["conf"] = round(min(0.99, max(0.5, rng.gauss(0.91, 0.04))), 3)
    if rng.random() < 0.30:
        mess.append("asr_substitutions")
        for t in turns:
            for word, subs in ASR_SUBS.items():
                if word in t["text"].lower() and rng.random() < 0.5:
                    i = t["text"].lower().find(word)
                    t["text"] = t["text"][:i] + rng.choice(subs) + t["text"][i + len(word):]
                    t["conf"] = round(t["conf"] - 0.08, 3)
    if garbled:
        mess.append("garbled_audio")
        for t in turns:
            words = t["text"].split()
            words = [("[inaudible]" if rng.random() < 0.4 else wd) for wd in words]
            t["text"] = " ".join(words)
            t["conf"] = round(rng.uniform(0.35, 0.62), 3)
    if rng.random() < 0.06 and len(turns) > 8:
        mess.append("cross_talk")
        i = rng.randrange(5, len(turns) - 2)
        a, b = turns[i], turns.pop(i + 1)
        a["text"] = f"{a['text']} [crosstalk] {b['text']}"
        a["conf"] = round(min(a["conf"], b["conf"]) - 0.1, 3)
        for it in truth["intents"]:  # keep the answer key's turn indices consistent
            for key in ("start_turn", "end_turn"):
                if it[key] > i:
                    it[key] -= 1
    if rng.random() < 0.05:
        mess.append("no_speaker_labels")
        for t in turns:
            t["speaker"] = None
    if truth["dropped"]:
        mess.append("dropped_call")
    truth["mess"] = mess


def survey(rng, truth):
    """Response bias: unhappy callers answer more. Score is noisy and pulled to the extremes."""
    p = {1: 0.60, 2: 0.48, 3: 0.27, 4: 0.22, 5: 0.28}[truth["csat"]]
    if rng.random() >= p:
        return None
    c = truth["csat"]
    r = rng.random()
    if r < 0.66:
        s = c
    elif r < 0.86:
        s = c + rng.choice([-1, 1])
    elif r < 0.95:
        s = 1 if c <= 3 else 5  # extremity: people round to the ends
    else:
        s = c + rng.choice([-2, 2])
    return min(5, max(1, s))


def annotate(rng, truth, lenient):
    """One simulated human annotator: right most of the time, off by one often, with a personal bias."""
    c = truth["csat"]
    r = rng.random()
    if r < 0.27:
        up = rng.random() < (0.65 if lenient else 0.35)
        c += 1 if up else -1
    elif r < 0.30:
        c += rng.choice([-2, 2])
    c = min(5, max(1, c))
    s = truth["sentiment"]
    if rng.random() < 0.17:
        s = {"happy": "mild", "not_happy": "mild"}.get(s) or rng.choice(["happy", "not_happy"])
    return c, s


def generate(seed: int = SEED, n_calls: int = N_CALLS, out: Path | None = None) -> dict:
    out = Path(out) if out else paths.DATA
    rng = random.Random(seed)
    agents = []
    for i, name in enumerate(AGENT_NAMES):
        agents.append({"id": f"A{i + 1:02d}", "name": name, "skill": round(rng.uniform(0.30, 0.90), 3),
                       "gaming": 0.5 if i in (3, 8) else 0.03})
    calls, truths = [], []
    for n in range(n_calls):
        agent = rng.choice(agents)
        call, truth = build_call(rng, f"C{n + 1:04d}", agent, rng.choice(DAYS))
        add_mess(rng, call, truth)
        calls.append(call)
        truths.append(truth)

    surveys = [(t["call_id"], s) for t in truths if (s := survey(rng, t)) is not None]

    golden_ids = sorted(rng.sample([c["call_id"] for c in calls], N_GOLDEN))
    shuffled = golden_ids[:]
    rng.shuffle(shuffled)
    dev, hold = set(shuffled[:N_DEV]), set(shuffled[N_DEV:])
    by_id = {t["call_id"]: t for t in truths}
    rows = []
    for cid in golden_ids:
        a = annotate(rng, by_id[cid], lenient=True)
        b = annotate(rng, by_id[cid], lenient=False)
        t = by_id[cid]
        # adjudication: a third reviewer resolves disagreements; simulated as recovering the latent label
        rows.append({"call_id": cid, "split": "dev" if cid in dev else "holdout",
                     "a_csat": a[0], "a_sentiment": a[1], "b_csat": b[0], "b_sentiment": b[1],
                     "adj_csat": t["csat"], "adj_sentiment": t["sentiment"]})

    (out / "golden").mkdir(parents=True, exist_ok=True)
    (out / "_answer_key").mkdir(parents=True, exist_ok=True)
    with open(out / "calls.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for c in calls:
            f.write(json.dumps(c) + "\n")
    with open(out / "surveys.csv", "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(["call_id", "survey_csat"])
        wr.writerows(surveys)
    fields = list(rows[0])
    for name, split in (("dev.csv", "dev"), ("holdout_sealed.csv", "holdout")):
        with open(out / "golden" / name, "w", encoding="utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            wr.writeheader()
            wr.writerows(r for r in rows if r["split"] == split)
    with open(out / "golden" / "splits.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"dev": sorted(dev), "holdout": sorted(hold)}, f, indent=0)
    with open(out / "_answer_key" / "truth.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for t in truths:
            f.write(json.dumps(t) + "\n")
    with open(out / "_answer_key" / "agents.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(agents, f, indent=1)
    return {"calls": len(calls), "surveys": len(surveys), "golden": len(rows), "dev": len(dev), "holdout": len(hold),
            "seed": seed}
