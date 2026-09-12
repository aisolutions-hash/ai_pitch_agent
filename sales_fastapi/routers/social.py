from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LinkedInProfile, RedditPost, User, WhatsAppMessage
from ..schemas import LinkedInSearchIn, RedditSearchIn, WhatsAppSendIn
from ..security import get_current_user
from ..services import LinkedInExtractor, RedditScraper

router = APIRouter(prefix="/social", tags=["social"])


# ---------- LinkedIn ----------
@router.get("/linkedin/profiles")
def list_linkedin(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(LinkedInProfile).filter(LinkedInProfile.user_id == user.id).all()


@router.post("/linkedin/search")
def search_linkedin(
    payload: LinkedInSearchIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extractor = LinkedInExtractor()
    found = extractor.search_by_hiring_alerts(payload.keywords, payload.location)
    added = 0
    for item in found:
        exists = (
            db.query(LinkedInProfile)
            .filter(
                LinkedInProfile.user_id == user.id,
                LinkedInProfile.profile_url == item["profile_url"],
            )
            .first()
        )
        if exists:
            continue
        db.add(
            LinkedInProfile(
                user_id=user.id,
                profile_url=item["profile_url"],
                name=item["name"],
                headline=item["headline"],
                company=item["company"],
                location=item["location"],
                skills=item["skills"],
                source_keyword=item["source_keyword"],
            )
        )
        added += 1
    db.commit()
    return {"found": len(found), "added": added, "api_available": extractor.available}


# ---------- Reddit ----------
@router.get("/reddit/posts")
def list_reddit(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(RedditPost).filter(RedditPost.user_id == user.id).all()


@router.post("/reddit/search")
def search_reddit(
    payload: RedditSearchIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scraper = RedditScraper()
    found = scraper.search_hiring_posts(payload.subreddits, payload.keywords)
    added = 0
    for item in found:
        exists = (
            db.query(RedditPost)
            .filter(RedditPost.user_id == user.id, RedditPost.post_url == item["post_url"])
            .first()
        )
        if exists:
            continue
        db.add(
            RedditPost(
                user_id=user.id,
                post_url=item["post_url"],
                title=item["title"],
                content=item["content"],
                subreddit=item["subreddit"],
                alerts_related=item["alerts_related"],
            )
        )
        added += 1
    db.commit()
    return {"found": len(found), "added": added, "api_available": scraper.available}


# ---------- WhatsApp ----------
@router.post("/whatsapp/messages", status_code=201)
def queue_whatsapp(
    payload: WhatsAppSendIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = WhatsAppMessage(
        user_id=user.id,
        phone_number=payload.phone_number,
        message=payload.message,
        status="pending",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return {"id": message.id, "status": message.status}


@router.get("/whatsapp/messages")
def list_whatsapp(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(WhatsAppMessage).filter(WhatsAppMessage.user_id == user.id).all()
