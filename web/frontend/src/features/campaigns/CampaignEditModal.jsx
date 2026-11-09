import { useMemo } from "react";
import { Modal } from "../../components/ui/Modal";
import { CampaignForm } from "./CampaignForm";

export function CampaignEditModal({
  campaign,
  formHook,
  pipelineConfig,
  onPipelineConfigChange,
  onLocationChange,
  onAddLocation,
  onRemoveLocation,
  pipelineConfigLoading = false,
  saving = false,
  skillSuggestions,
  onClose,
  onSave,
}) {
  const {
    campaignForm,
    updateForm,
    skillInput,
    setSkillInput,
    formError,
    sampleCvRef,
    selectedSkills,
    addSkill,
    removeSkill,
    handleSkillKeyDown,
    handleCvUpload,
  } = formHook;

  const availableSkillSuggestions = useMemo(() => {
    const lowerSelected = selectedSkills.map((skill) => skill.toLowerCase());
    const filterValue = skillInput.trim().toLowerCase();

    return skillSuggestions
      .filter((skill) => !lowerSelected.includes(skill.toLowerCase()))
      .filter(
        (skill) => !filterValue || skill.toLowerCase().includes(filterValue)
      )
      .slice(0, 8);
  }, [skillInput, selectedSkills, skillSuggestions]);

  if (!campaign) return null;

  return (
    <Modal title="Edit Campaign" onClose={onClose} size="max-w-5xl">
      <CampaignForm
        form={campaignForm}
        updateForm={updateForm}
        pipelineConfig={pipelineConfig}
        onPipelineConfigChange={onPipelineConfigChange}
        onLocationChange={onLocationChange}
        onAddLocation={onAddLocation}
        onRemoveLocation={onRemoveLocation}
        pipelineConfigLoading={pipelineConfigLoading}
        saving={saving}
        skillInput={skillInput}
        setSkillInput={setSkillInput}
        selectedSkills={selectedSkills}
        availableSkillSuggestions={availableSkillSuggestions}
        addSkill={addSkill}
        removeSkill={removeSkill}
        handleSkillKeyDown={handleSkillKeyDown}
        handleCvUpload={handleCvUpload}
        sampleCvRef={sampleCvRef}
        formError={formError}
        onClose={onClose}
        onSave={onSave}
        submitLabel="Update Campaign"
        isModal={true}
      />
    </Modal>
  );
}