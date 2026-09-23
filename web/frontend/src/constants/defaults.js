export const DEFAULT_SKILL_SUGGESTIONS = [
  "Python",
  "SQL",
  "Machine Learning",
  "Deep Learning",
  "NLP",
  "Computer Vision",
  "MLOps",
  "FastAPI",
  "Django",
  "Flask",
  "PostgreSQL",
  "MongoDB",
  "AWS",
  "Azure",
  "GCP",
  "Docker",
  "Kubernetes",
  "PyTorch",
  "TensorFlow",
  "Scikit-learn",
  "Spark",
  "Airflow",
  "React",
  "TypeScript",
  "Node.js",
  "B2B SaaS",
  "Roadmap",
  "Analytics",
  "Experimentation",
  "Vector DB",
  "LangChain",
  "RAG",
];

// Short labels for the run-progress stepper. The pipeline reports the same phase keys in
// data/pipeline_status.json (see candidate_pool/scripts/pipeline_status.py, which carries the
// longer sentence-style label used for the active phase).
export const PIPELINE_PHASE_LABELS = {
  queries: "Queries",
  search: "Search",
  filter: "AI review",
  ranking: "Ranking",
  report: "Report",
};

export const EMPTY_CAMPAIGN_FORM = {
  campaignName: "",
  location: "",
  positionName: "",
  desiredSkillsText: "",
  experience: "3-5",
  sampleCvFile: null,
  targetProfiles: 25,
  status: "Active",
};