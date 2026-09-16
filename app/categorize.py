"""Guesses a category from a merchant name.

Two layers: keyword rules that ship with the app, and rules the app learns
whenever you correct a category in the review screen. Learned rules win.
"""

import re
import unicodedata

from . import db

OTHER = "Other"
PAYMENTS = "Payments & Refunds"

CATEGORIES = [
    "Food & Dining",
    "Groceries",
    "Transport",
    "Travel",
    "Shopping",
    "Entertainment",
    "Subscriptions",
    "Health",
    "Bills & Utilities",
    "Home",
    "Education",
    "Pets",
    "Fees & Interest",
    PAYMENTS,
    OTHER,
]

# Keywords are matched against an accent-stripped, lowercased merchant name.
# Longest keyword wins, and ties go to whichever category is listed first, so
# categories with generic words ("shopping", "store") are kept near the bottom.
KEYWORD_RULES: dict[str, list[str]] = {
    "Food & Dining": [
        # "ifd" is the acquirer prefix iFood shows up as on card statements.
        "ifood", "ifd", "rappi", "ubereats", "uber eats", "doordash", "grubhub",
        "restaurante", "restaurant", "lanchonete", "pizzaria", "pizza",
        "burger", "hamburgueria", "mcdonald", "bk", "burger king", "subway",
        "starbucks", "cafe", "café", "cafeteria", "coffee", "padaria",
        "bakery", "bar ", "pub", "boteco", "churrascaria", "sushi", "temaki",
        "japones", "cantina", "bistro", "food", "kitchen", "grill", "acai",
        "açai", "sorveteria", "gelato", "doceria", "confeitaria", "esfiha",
        "pastel", "spoleto", "outback", "habib", "giraffas", "bob s",
        "delivery", "chopp", "cervejaria", "brewery", "dominos", "kfc",
    ],
    "Groceries": [
        "supermercado", "mercado", "hortifruti", "acougue", "açougue",
        "quitanda", "mercearia", "emporio", "empório", "grocery", "market",
        "armazem", "armazém", "armazemdocampo", "padoca", "feira",
        "carrefour", "pao de acucar", "pão de açúcar", "extra", "assai",
        "assaí", "atacadao", "atacadão", "big bompreco", "bompreco", "dia",
        "sam s club", "costco", "walmart", "whole foods", "trader joe",
        "safeway", "kroger", "aldi", "lidl", "tesco", "zona sul", "prezunic",
        "sendas", "st marche", "oba hortifruti", "mambo",
    ],
    "Transport": [
        # 99 is a Brazilian ride app; it bills as "99*" or "99 Tecnologia".
        "uber", "99", "99pop", "99 pop", "99app", "99 tecnologia", "cabify", "lyft",
        "taxi", "táxi", "metro", "metrô", "cptm", "sptrans", "bilhete unico",
        "bilhete único", "riocard", "onibus", "ônibus", "bus", "brt",
        "estacionamento", "parking", "estapar", "zona azul", "posto",
        "gasolina", "combustivel", "combustível", "shell", "ipiranga",
        "petrobras", "br mania", "ale combustiveis", "gas station", "chevron",
        "exxon", "pedagio", "pedágio", "toll", "sem parar", "conectcar",
        "veloe", "autopass", "yellow", "grin", "tembici", "bike", "car rental",
        "localiza", "movida", "unidas", "hertz", "avis",
    ],
    "Travel": [
        "latam", "gol linhas", "gol transportes", "azul linhas", "voepass",
        "airlines", "airline", "american air", "united air", "delta air",
        "iberia", "tap portugal", "air france", "emirates", "airbnb",
        "booking.com", "booking com", "hotel", "hostel", "pousada", "resort",
        "expedia", "decolar", "despegar", "kayak", "trivago", "cvc viagens",
        "123milhas", "maxmilhas", "hoteis", "hotéis", "aeroporto", "airport",
        "duty free",
    ],
    "Entertainment": [
        "cinema", "cinemark", "cinepolis", "kinoplex", "uci cinemas",
        "ingresso.com", "ingressos", "sympla", "eventim", "ticketmaster",
        "teatro", "theatre", "show", "festival", "steam", "steamgames",
        "playstation", "xbox", "nintendo", "epic games", "riot games",
        "blizzard", "twitch", "game", "boliche", "parque", "zoo", "museu",
        "museum",
    ],
    "Subscriptions": [
        "netflix", "spotify", "deezer", "tidal", "youtube premium",
        "youtubepremium", "google one", "google storage", "icloud",
        "apple.com/bill", "apple com bill", "apple music", "hbo", "max.com",
        "disney", "star+", "starplus", "paramount", "globoplay", "primevideo",
        "prime video", "amazon prime", "crunchyroll", "openai", "chatgpt",
        "anthropic", "claude.ai", "midjourney", "github", "notion", "figma",
        "adobe", "microsoft 365", "office 365", "dropbox", "canva",
        "linkedin premium", "audible", "kindle unlimited", "assinatura",
        "subscription", "medium", "substack", "cursor",
    ],
    "Health": [
        "farmacia", "farmácia", "drogaria", "droga raia", "drogasil",
        "pacheco", "pague menos", "panvel", "pharmacy", "cvs", "walgreens",
        "hospital", "clinica", "clínica", "laboratorio", "laboratório",
        "labi exames", "fleury", "dasa", "sabin", "einstein", "sirio libanes",
        "sírio libanês", "dentista", "dental", "odonto", "psicolog",
        "terapia", "therapy", "medico", "médico", "doctor", "consulta",
        "unimed", "amil", "sulamerica", "sulamérica", "bradesco saude",
        "hapvida", "notredame", "academia", "smart fit", "smartfit",
        "bluefit", "bio ritmo", "gym", "fitness", "crossfit", "pilates",
        "yoga", "wellhub", "gympass", "totalpass",
    ],
    "Bills & Utilities": [
        "vivo", "claro", "tim ", "tim s.a", "oi fibra", "oi movel", "nextel",
        "at t", "verizon", "t-mobile", "internet", "banda larga", "telefonica",
        "telefônica", "net servicos", "sky brasil", "energia", "eletropaulo",
        "enel", "cemig", "copel", "light servicos", "celpe", "coelba",
        "neoenergia", "cpfl", "equatorial", "sabesp", "cedae", "agua",
        "água", "water", "comgas", "comgás", "naturgy", "gas natural",
        "electric", "utility", "conta de luz", "boleto",
    ],
    "Home": [
        "aluguel", "rent", "condominio", "condomínio", "iptu", "imobiliaria",
        "imobiliária", "marcenaria", "reforma", "construcao", "construção",
        "material de construcao", "obramax", "cec ", "tok stok", "tokstok",
        "mobly", "madeiramadeira", "westwing", "camicado", "utilidades",
        "faxina", "diarista", "cleaning",
    ],
    "Education": [
        "escola", "school", "colegio", "colégio", "universidade", "faculdade",
        "university", "college", "curso", "course", "udemy", "coursera",
        "alura", "rocketseat", "duolingo", "babbel", "cambly", "livraria",
        "bookstore", "amazon kindle", "estacio", "estácio", "anhanguera",
        "fgv", "usp", "puc", "senac", "sesi", "mensalidade", "tuition",
    ],
    "Pets": [
        "petz", "cobasi", "petlove", "petshop", "pet shop", "veterinaria",
        "veterinária", "veterinario", "veterinário", "vet ", "racao",
        "ração", "chewy", "petco",
    ],
    "Fees & Interest": [
        "anuidade", "tarifa", "juros", "interest", "iof", "multa",
        "encargos", "annual fee", "late fee", "finance charge", "taxa",
        "saque", "cash advance", "atm fee", "rendimento negativo",
    ],
    PAYMENTS: [
        "pagamento recebido", "pagamento de fatura", "payment received",
        "payment thank you", "estorno", "reembolso", "refund", "chargeback",
        "credito recebido", "crédito recebido", "cashback", "devolucao",
        "devolução", "ajuste a credito",
    ],
    # Last on purpose: "loja", "store" and "shopping" are weak signals that
    # should lose to any more specific match of the same length.
    "Shopping": [
        "amazon", "mercadolivre", "mercado livre", "mercadopago",
        "shopee", "aliexpress", "shein", "magazine luiza", "magalu",
        "americanas", "casas bahia", "ponto frio", "submarino", "kabum",
        "kabum!", "terabyte", "pichau", "renner", "c a modas", "riachuelo",
        "zara", "h m", "hering", "nike", "adidas", "centauro", "decathlon",
        "netshoes", "leroy merlin", "telhanorte", "ikea", "etsy", "ebay",
        "target", "best buy", "apple store", "loja", "store", "shop",
        "boutique", "outlet", "shopping",
    ],
}


def normalize(text: str) -> str:
    """Lowercase, strip accents, collapse punctuation to spaces."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_text = decomposed.encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def _matches(haystack: str, keyword: str) -> bool:
    needle = normalize(keyword)
    if not needle:
        return False
    # Word-boundary match for single short tokens, substring otherwise, so
    # "dia" does not fire inside "diagnostico".
    if " " not in needle and len(needle) <= 4:
        return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
    return needle in haystack


def categorize(merchant: str, amount_cents: int = 0,
               learned: dict[str, str] | None = None,
               hint: str | None = None) -> str:
    """Best guess for a merchant's category.

    `hint` is a category the source itself supplied — the bank's own label on a
    statement row. It outranks our keyword guessing, because the bank knows what
    it billed, but it loses to a rule you taught the app by hand.
    """
    if amount_cents < 0:
        return PAYMENTS

    haystack = normalize(merchant)
    if not haystack:
        return hint or OTHER

    if learned is None:
        try:
            learned = db.all_merchant_rules()
        except Exception:
            learned = {}

    # Longest learned pattern first: the most specific rule should win.
    for pattern in sorted(learned, key=len, reverse=True):
        normalized = normalize(pattern)
        if normalized and normalized in haystack:
            return learned[pattern]

    if hint:
        return hint

    best: tuple[int, str] | None = None
    for category, keywords in KEYWORD_RULES.items():
        for keyword in keywords:
            if _matches(haystack, keyword):
                score = len(normalize(keyword))
                if best is None or score > best[0]:
                    best = (score, category)
    return best[1] if best else OTHER


def learn(merchant: str, category: str) -> None:
    """Remembers a manual correction so the next import gets it right."""
    if not merchant or not category or category == OTHER:
        return
    key = normalize(merchant)
    if len(key) < 3:
        return
    db.remember_merchant(key, category)
