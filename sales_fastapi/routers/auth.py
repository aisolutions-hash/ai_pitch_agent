from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import GoogleLoginIn, TokenOut, UserOut
from ..security import (
    create_access_token,
    get_current_user,
    verify_google_id_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _domain_of(email_address: str) -> str:
    return email_address.split("@")[-1].lower() if "@" in email_address else ""


@router.post("/google", response_model=TokenOut)
def google_login(payload: GoogleLoginIn, db: Session = Depends(get_db)) -> TokenOut:
    claims = verify_google_id_token(payload.id_token)
    email_address = claims["email"].lower()

    user = db.query(User).filter(User.email == email_address).first()
    if user is None:
        user = User(
            google_sub=claims.get("sub", email_address),
            email=email_address,
            name=claims.get("name", ""),
            picture=claims.get("picture", ""),
            domain=_domain_of(email_address),
        )
        db.add(user)
    else:
        user.name = claims.get("name", user.name)
        user.picture = claims.get("picture", user.picture)
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    token, expires_in = create_access_token(user)
    return TokenOut(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
