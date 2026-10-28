export interface Member {
  id: string;
  name: string;
  scenario: string;
  prompts: string[];
}

// Demo members from seed-data/fixtures. Scenarios mirror the seeded claims,
// appointments and prescriptions; prompts are one-click starters for demos and testing.
const CLAIMS = "What's the status of my claims?";
const APPT = "When's my next appointment?";
const RX = "What prescriptions do I have on file?";
const DENIED = "Why was my claim denied?";
const RESCHEDULE = "I need to reschedule my appointment.";
const OUT_OF_SCOPE = "Can you diagnose my knee pain?";

const m = (n: string, name: string, scenario: string, ...prompts: string[]): Member => ({
  id: `MBR-DEMO-000${n}`,
  name,
  scenario,
  prompts: [...prompts, OUT_OF_SCOPE],
});

export const MEMBERS: Member[] = [
  m("101", "Alicia Renner", "paid claim, appointment, Lisinopril + Atorvastatin refills",
    CLAIMS, APPT, "Can I refill my Lisinopril?", "Can I refill my Atorvastatin early?"),
  m("102", "Marcus Okafor", "paid claim, appointment, Humira prior auth pending",
    CLAIMS, APPT, "What's the status of my Humira prior authorization?"),
  m("103", "Priya Deshmukh", "paid claim, appointment, Ozempic prior auth denied",
    CLAIMS, APPT, "Can I get a refill on my Ozempic?", "So what do I do now?"),
  m("104", "Devon Marsh", "paid claim, Metformin + Albuterol refills",
    CLAIMS, "I need a refill on my Metformin, please.", "How many refills are left on my Albuterol inhaler?"),
  m("105", "Sofia Alvarez", "paid claim, expired Amoxicillin",
    CLAIMS, "Can I refill my Amoxicillin?", RX),
  m("106", "Wei Chen", "denied claim (no precert), needs appeal", DENIED, "Can I appeal it?", "How long do I have to appeal?"),
  m("107", "Grace Whitfield", "denied claim (out of network)",
    "Look up my specialist visit claim.", DENIED, "What will I owe?"),
  m("108", "Omar Haddad", "denied claim, Sertraline refill",
    DENIED, "Does my Sertraline need prior authorization?", "I need a refill on my Sertraline."),
  m("109", "Nadia Kessler", "claim in review", CLAIMS, "Why is my claim still in review?"),
  m("110", "Ethan Boone", "claim in review", CLAIMS, "Why is my claim still in review?"),
  m("111", "Renata Ferreira", "paid + denied claims", "What's going on with my claims?", DENIED),
  m("112", "Kwame Nakamura", "paid + denied claims, Levothyroxine not yet refillable",
    "What's going on with my claims?", "Can I refill my Levothyroxine early? I'm about to run out."),
  m("113", "Ines Voss", "upcoming appointment", APPT, "Who is my appointment with?", RESCHEDULE),
  m("114", "Julian Larkin", "upcoming appointment", APPT, "Is my appointment telehealth or in person?"),
  m("115", "Farah Aziz", "upcoming appointment", APPT, "Where is my appointment?"),
  m("116", "Tobias Petrov", "upcoming appointment", APPT, RESCHEDULE),
  m("117", "Amara Nwosu", "appointment to reschedule", APPT, RESCHEDULE),
  m("118", "Leo Byrne", "appointment to reschedule, Montelukast refill",
    RESCHEDULE, "Can I refill my Montelukast?"),
  m("119", "Simone Kaur", "same-day appointment (reschedule blocked)",
    "I need to reschedule my appointment today to a different time."),
  m("120", "Hiro Solis", "no upcoming appointments", "Any appointments coming up?", RX),
  m("121", "Delia Renner", "no upcoming appointments", "Any appointments coming up?", RX),
  m("122", "Anders Okafor", "lapsed enrollment", CLAIMS, "Am I still enrolled?"),
];
