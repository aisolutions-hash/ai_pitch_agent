# pitch_generator/models.py
from django.db import models
from django.conf import settings


def get_user_model():
    return settings.AUTH_USER_MODEL


class LeadPitch(models.Model):
    user = models.ForeignKey(
        get_user_model(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='lead_pitches',
        help_text='The user who created this pitch.'
    )
    company_name = models.CharField(max_length=255)
    website_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Research Insights
    pain_points = models.TextField(help_text="Identified gaps like 'No social presence' or 'Slow site'")
    research_summary = models.TextField(blank=True)

    # Generated Content (Text)
    email_subject = models.CharField(max_length=255, blank=True)
    email_body_text = models.TextField(help_text="Professional text-only email")
    email_body_html = models.TextField(help_text="Attractive HTML email template")
    whatsapp_message = models.TextField(help_text="Conversational short message")
    call_script = models.TextField(help_text="Phone script for sales rep")

    # --- NEW: VISUAL PROOF FIELDS ---
    visual_style_guide = models.TextField(
        help_text="AI's analysis of the brand's likely color palette and aesthetic",
        blank=True
    )
    image_prompt = models.TextField(
        help_text="Midjourney/DALL-E prompt with technical camera specs",
        blank=True
    )
    video_prompt = models.TextField(
        help_text="Runway/Luma prompt with camera movement and motion description",
        blank=True
    )

    def __str__(self):
        return f"Pitch for {self.company_name}"