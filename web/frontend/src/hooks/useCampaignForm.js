import { useMemo, useRef, useState } from "react";
import { EMPTY_CAMPAIGN_FORM } from "../constants/defaults";

export function useCampaignForm(initialForm = EMPTY_CAMPAIGN_FORM) {
  const [campaignForm, setCampaignForm] = useState(initialForm);
  const [skillInput, setSkillInput] = useState("");
  const [formError, setFormError] = useState("");
  const sampleCvRef = useRef(null);

  const selectedSkills = useMemo(() => {
    return campaignForm.desiredSkillsText
      .split(",")
      .map((skill) => skill.trim())
      .filter(Boolean);
  }, [campaignForm.desiredSkillsText]);

  const updateForm = (field, value) => {
    setCampaignForm((previousForm) => ({
      ...previousForm,
      [field]: value,
    }));

    setFormError("");
  };

  const resetForm = (nextForm = EMPTY_CAMPAIGN_FORM) => {
    setCampaignForm(nextForm);
    setSkillInput("");
    setFormError("");

    if (sampleCvRef.current) {
      sampleCvRef.current.value = "";
    }
  };

  const addSkill = (skill) => {
    const cleanSkill = skill.trim();

    if (!cleanSkill) return;

    const existingSkills = selectedSkills.map((item) => item.toLowerCase());

    if (existingSkills.includes(cleanSkill.toLowerCase())) {
      setSkillInput("");
      return;
    }

    updateForm("desiredSkillsText", [...selectedSkills, cleanSkill].join(", "));
    setSkillInput("");
  };

  const removeSkill = (skillToRemove) => {
    const nextSkills = selectedSkills.filter(
      (skill) => skill !== skillToRemove
    );

    updateForm("desiredSkillsText", nextSkills.join(", "));
  };

  const handleSkillKeyDown = (event) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addSkill(skillInput);
    }
  };

  const handleCvUpload = (event) => {
    const file = event.target.files?.[0];

    if (!file) return;

    const isPdf =
      file.type === "application/pdf" ||
      file.name.toLowerCase().endsWith(".pdf");

    if (!isPdf) {
      setFormError("Sample CV must be a PDF file.");
      event.target.value = "";
      updateForm("sampleCvFile", null);
      return;
    }

    updateForm("sampleCvFile", file);
  };

  return {
    campaignForm,
    setCampaignForm,
    skillInput,
    setSkillInput,
    formError,
    setFormError,
    sampleCvRef,
    selectedSkills,
    updateForm,
    resetForm,
    addSkill,
    removeSkill,
    handleSkillKeyDown,
    handleCvUpload,
  };
}