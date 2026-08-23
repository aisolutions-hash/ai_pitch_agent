# pitch_generator/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import LeadPitch
# Import the new export function here
from .utils import perform_research, generate_pitch_content, export_to_google_sheets


@login_required
def create_pitch(request):
    if request.method == "POST":
        company_name = request.POST.get('company_name')
        website_url = request.POST.get('website_url')

        if not company_name:
            messages.error(request, "Company Name is required.")
            return redirect('pitch_generator:create_pitch')

        try:
            # 1. Research
            research_summary = perform_research(company_name, website_url)
            
            # 2. AI Generation
            content = generate_pitch_content(company_name, research_summary)

            # 3. Save to DB
            pitch = LeadPitch.objects.create(
                user=request.user,
                company_name=company_name,
                website_url=website_url,
                research_summary=research_summary,
                
                # Text Content
                pain_points=content.get('pain_points', ''),
                email_subject=content.get('email_subject', ''),
                email_body_text=content.get('email_body_text', ''),
                email_body_html=content.get('email_body_html', ''),
                whatsapp_message=content.get('whatsapp_message', ''),
                call_script=content.get('call_script', ''),
                
                # Visual Content
                visual_style_guide=content.get('visual_style_guide', ''),
                image_prompt=content.get('image_prompt', ''),
                video_prompt=content.get('video_prompt', '')
            )

            # --- 4. EXPORT TO GOOGLE SHEETS ---
            export_data = {
                'company_name': company_name,
                'website_url': website_url,
                'pain_points': pitch.pain_points,
                'email_subject': pitch.email_subject,
                'email_body_text': pitch.email_body_text, # Added this
                'whatsapp_message': pitch.whatsapp_message,
                'visual_style_guide': pitch.visual_style_guide,
                'image_prompt': pitch.image_prompt,
                'video_prompt': pitch.video_prompt
            }
            # Execute export (Errors are printed to console so they don't block the UI)
            export_to_google_sheets(export_data)
            
            return redirect('pitch_generator:view_pitch', pitch_id=pitch.id)

        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('pitch_generator:create_pitch')

    # --- FETCH HISTORY FOR UI TABLE ---
    recent_pitches = LeadPitch.objects.filter(user=request.user).order_by('-created_at')
    
    return render(request, 'pitch_generator/create_pitch.html', {'recent_pitches': recent_pitches})


@login_required
def view_pitch(request, pitch_id):
    pitch = get_object_or_404(LeadPitch, id=pitch_id, user=request.user)
    return render(request, 'pitch_generator/view_pitch.html', {'pitch': pitch})