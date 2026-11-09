/**
 * Resolves a candidate's discovery source and profile URL into a consistent
 * platform badge descriptor (emoji, human-readable label, and styling classes).
 */
export function getSourcePlatformInfo(source, profileUrl = "") {
  const rawSource = String(source || "").trim().toLowerCase();
  const rawUrl = String(profileUrl || "").trim().toLowerCase();

  if (rawSource === "github" || rawUrl.includes("github.com")) {
    return {
      key: "github",
      emoji: "🐙",
      label: "GitHub",
      display: "🐙 GitHub",
      profileButtonLabel: "🐙 GitHub Profile",
      pillClass: "bg-slate-900 text-white border border-slate-800",
    };
  }

  if (
    rawSource === "huggingface" ||
    rawSource === "hf" ||
    rawUrl.includes("huggingface.co")
  ) {
    return {
      key: "huggingface",
      emoji: "🤗",
      label: "Hugging Face",
      display: "🤗 Hugging Face",
      profileButtonLabel: "🤗 Hugging Face Profile",
      pillClass: "bg-amber-100 text-amber-900 border border-amber-300",
    };
  }

  if (rawSource === "kaggle" || rawUrl.includes("kaggle.com")) {
    return {
      key: "kaggle",
      emoji: "🏆",
      label: "Kaggle",
      display: "🏆 Kaggle",
      profileButtonLabel: "🏆 Kaggle Profile",
      pillClass: "bg-sky-100 text-sky-900 border border-sky-300",
    };
  }

  if (
    rawSource === "exa" ||
    rawSource === "linkedin" ||
    rawUrl.includes("linkedin.com")
  ) {
    return {
      key: "exa",
      emoji: "🔍",
      label: "Exa.ai",
      display: "🔍 Exa.ai",
      profileButtonLabel: rawUrl.includes("linkedin.com")
        ? "💼 LinkedIn Profile"
        : "🔍 Open Profile",
      pillClass: "bg-indigo-100 text-indigo-800 border border-indigo-200",
    };
  }

  if (rawSource === "peopledatalabs" || rawSource === "pdl") {
    return {
      key: "peopledatalabs",
      emoji: "📊",
      label: "PeopleDataLabs",
      display: "📊 PeopleDataLabs",
      profileButtonLabel: "📊 Open Profile",
      pillClass: "bg-purple-100 text-purple-800 border border-purple-200",
    };
  }

  if (rawSource === "apollo") {
    return {
      key: "apollo",
      emoji: "🚀",
      label: "Apollo",
      display: "🚀 Apollo",
      profileButtonLabel: "🚀 Open Profile",
      pillClass: "bg-emerald-100 text-emerald-800 border border-emerald-200",
    };
  }

  const fallbackLabel = source || "Candidate Pool";
  return {
    key: "other",
    emoji: "🌐",
    label: fallbackLabel,
    display: `🌐 ${fallbackLabel}`,
    profileButtonLabel: "🌐 Open Profile",
    pillClass: "bg-slate-100 text-slate-700 border border-slate-200",
  };
}
