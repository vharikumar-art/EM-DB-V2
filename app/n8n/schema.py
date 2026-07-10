from pydantic import BaseModel


class StartCampaignRequest(BaseModel):
    profileId: str


class StartCampaignResponse(BaseModel):
    status: str
    profileId: str
    webhookAccepted: bool
