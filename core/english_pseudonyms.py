"""
Базы английских псевдонимов для деанонимизации.
Города, компании, фамилии — используются как замены при анонимизации.
"""

# Английские города (100 штук, разнообразные)
ENGLISH_CITIES = [
    "London", "Manchester", "Bristol", "Cambridge", "Oxford",
    "Liverpool", "Birmingham", "Edinburgh", "Glasgow", "Leeds",
    "Sheffield", "Nottingham", "Brighton", "York", "Bath",
    "Canterbury", "Durham", "Chester", "Exeter", "Lancaster",
    "Winchester", "Stratford", "Plymouth", "Norwich", "Derby",
    "Coventry", "Sunderland", "Bradford", "Leicester", "Wakefield",
    "Carlisle", "Newport", "Swansea", "Aberdeen", "Dundee",
    "Inverness", "Perth", "Stirling", "Blackpool", "Bournemouth",
    "Eastbourne", "Hastings", "Ipswich", "Colchester", "Gloucester",
    "Worcester", "Hereford", "Shrewsbury", "Stafford", "Lichfield",
    "Warwick", "Lincoln", "Peterborough", "Northampton", "Milton Keynes",
    "Luton", "Reading", "Guildford", "Rochester", "Maidstone",
    "Truro", "Salisbury", "Taunton", "Wells", "Ripon",
    "Chichester", "Bangor", "St Albans", "Chelmsford", "Wolverhampton",
    "Stoke-on-Trent", "Kingston upon Hull", "Doncaster", "Barnsley", "Rotherham",
    "Huddersfield", "Halifax", "Dewsbury", "Harrogate", "Scarborough",
    "Darlington", "Hartlepool", "Middlesbrough", "Stockton", "Gateshead",
    "South Shields", "Tynemouth", "Whitby", "Kendal", "Penrith",
    "Workington", "Barrow", "Douglas", "Ayr", "Dumfries",
    "Falkirk", "Kilmarnock", "Paisley", "Greenock", "Elgin",
]

# Английские компании (вымышленные, правдоподобные)
ENGLISH_COMPANIES = [
    "Northgate Industries Ltd",
    "Meridian Solutions Corp",
    "Ashford & Partners Inc",
    "Sterling Dynamics Ltd",
    "Blackwood Engineering Co",
    "Harrington Global Services",
    "Crossfield Manufacturing Ltd",
    "Whitmore Technical Group",
    "Oakridge Systems Inc",
    "Pemberton & Hayes Ltd",
    "Kingsford Logistics Co",
    "Silverdale Resources Ltd",
    "Thornhill Enterprises Inc",
    "Westbrook Capital Ltd",
    "Briarwood Solutions Group",
    "Fairmont Industrial Corp",
    "Eastgate Trading Ltd",
    "Hillcrest Energy Inc",
    "Lockwood & Associates",
    "Crestview Holdings Ltd",
    "Hartfield Services Corp",
    "Redstone Technologies Ltd",
    "Clearwater Industries Inc",
    "Alderton Group Ltd",
    "Foxwell Engineering Co",
    "Brookside Chemicals Ltd",
    "Glenmore Supply Chain Inc",
    "Whitehall Consulting Ltd",
    "Langford Construction Co",
    "Riverside Petroleum Ltd",
    "Ashbury Metals Inc",
    "Windermere Power Corp",
    "Stratton Aerospace Ltd",
    "Belmont Oil & Gas Co",
    "Moorfield Environmental Ltd",
    "Dunmore Mining Corp",
    "Greenfield Renewables Ltd",
    "Castleford Transport Inc",
    "Highgate Pharmaceuticals Ltd",
    "Newbury Defence Systems Co",
]

# Английские мужские имена
ENGLISH_MALE_FIRST = [
    "James", "John", "Robert", "Michael", "William",
    "David", "Richard", "Thomas", "Charles", "Christopher",
    "Daniel", "Matthew", "Anthony", "Mark", "Steven",
    "Andrew", "Paul", "Joshua", "Kenneth", "George",
    "Edward", "Brian", "Ronald", "Timothy", "Jason",
    "Jeffrey", "Ryan", "Jacob", "Gary", "Nicholas",
    "Eric", "Jonathan", "Stephen", "Larry", "Justin",
    "Scott", "Brandon", "Benjamin", "Samuel", "Raymond",
    "Gregory", "Frank", "Patrick", "Alexander", "Jack",
    "Henry", "Peter", "Nathan", "Philip", "Arthur",
]

# Английские женские имена
ENGLISH_FEMALE_FIRST = [
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara",
    "Elizabeth", "Susan", "Jessica", "Sarah", "Karen",
    "Lisa", "Nancy", "Betty", "Margaret", "Sandra",
    "Ashley", "Dorothy", "Kimberly", "Emily", "Donna",
    "Michelle", "Carol", "Amanda", "Melissa", "Deborah",
    "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia",
    "Kathleen", "Amy", "Angela", "Shirley", "Anna",
    "Brenda", "Pamela", "Emma", "Nicole", "Helen",
    "Samantha", "Katherine", "Christine", "Debra", "Rachel",
    "Carolyn", "Janet", "Catherine", "Maria", "Heather",
]

# Английские фамилии
ENGLISH_SURNAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Anderson", "Taylor", "Thomas", "Moore", "Jackson",
    "Martin", "Lee", "Thompson", "White", "Harris",
    "Clark", "Lewis", "Robinson", "Walker", "Young",
    "Allen", "King", "Wright", "Scott", "Torres",
    "Hill", "Green", "Adams", "Baker", "Nelson",
    "Carter", "Mitchell", "Perez", "Roberts", "Turner",
    "Phillips", "Campbell", "Parker", "Evans", "Edwards",
    "Collins", "Stewart", "Morris", "Rogers", "Reed",
    "Cook", "Morgan", "Bell", "Murphy", "Bailey",
    "Rivera", "Cooper", "Richardson", "Cox", "Howard",
    "Ward", "Brooks", "Watson", "Wood", "Bennett",
    "Gray", "Henderson", "Coleman", "Jenkins", "Perry",
    "Powell", "Russell", "Sullivan", "Foster", "Hayes",
    "Simmons", "Fisher", "Webb", "Simpson", "Stevens",
    "Tucker", "Porter", "Hunter", "Hicks", "Crawford",
    "Henry", "Boyd", "Mason", "Palmer", "Harvey",
    "Burton", "Knight", "Chapman", "Grant", "Spencer",
    "Lawson", "Hart", "Bishop", "Barker", "Doyle",
]

# Английские отчества (middlе initials)
ENGLISH_MIDDLE_INITIALS = list("ABCDEFGHJKLMNPRSTW")


class EnglishPseudonymGenerator:
    """Генератор английских псевдонимов с гарантией уникальности."""

    def __init__(self):
        self._city_idx = 0
        self._company_idx = 0
        self._surname_idx = 0
        self._first_male_idx = 0
        self._first_female_idx = 0
        self._used_cities = set()
        self._used_companies = set()
        self._used_names = set()

    def next_city(self) -> str:
        """Следующий уникальный английский город."""
        city = ENGLISH_CITIES[self._city_idx % len(ENGLISH_CITIES)]
        self._city_idx += 1
        return city

    def next_company(self) -> str:
        """Следующая уникальная английская компания."""
        company = ENGLISH_COMPANIES[self._company_idx % len(ENGLISH_COMPANIES)]
        self._company_idx += 1
        return company

    def next_full_name(self, gender: str = "male") -> str:
        """Следующее уникальное английское ФИО (First M. Last)."""
        if gender == "female":
            first = ENGLISH_FEMALE_FIRST[self._first_female_idx % len(ENGLISH_FEMALE_FIRST)]
            self._first_female_idx += 1
        else:
            first = ENGLISH_MALE_FIRST[self._first_male_idx % len(ENGLISH_MALE_FIRST)]
            self._first_male_idx += 1

        surname = ENGLISH_SURNAMES[self._surname_idx % len(ENGLISH_SURNAMES)]
        mid = ENGLISH_MIDDLE_INITIALS[self._surname_idx % len(ENGLISH_MIDDLE_INITIALS)]
        self._surname_idx += 1

        return f"{first} {mid}. {surname}"

    def next_surname_with_initials(self) -> str:
        """Следующая фамилия с инициалами: J.R. Smith."""
        surname = ENGLISH_SURNAMES[self._surname_idx % len(ENGLISH_SURNAMES)]
        first = ENGLISH_MALE_FIRST[self._first_male_idx % len(ENGLISH_MALE_FIRST)]
        mid = ENGLISH_MIDDLE_INITIALS[self._surname_idx % len(ENGLISH_MIDDLE_INITIALS)]
        self._surname_idx += 1
        self._first_male_idx += 1
        return f"{first[0]}.{mid}. {surname}"

    def next_surname_only(self) -> str:
        """Только фамилия."""
        surname = ENGLISH_SURNAMES[self._surname_idx % len(ENGLISH_SURNAMES)]
        self._surname_idx += 1
        return surname
