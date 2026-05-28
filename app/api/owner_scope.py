from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models.gmail_correo import GmailCorreo
from app.models.siniestro import Siniestro


def siniestro_owner_filter(owner_email: str):
    owned_correo_ids = select(GmailCorreo.id).where(GmailCorreo.owner_email == owner_email)
    return or_(
        Siniestro.owner_email == owner_email,
        Siniestro.gmail_correo_id.in_(owned_correo_ids),
    )


def siniestro_scope(owner_email: str) -> Select[tuple[Siniestro]]:
    return select(Siniestro).where(siniestro_owner_filter(owner_email))


def find_siniestro_for_owner(db: Session, id_siniestro: str, owner_email: str) -> Siniestro | None:
    base = siniestro_scope(owner_email)

    siniestro = db.scalar(base.where(Siniestro.id_siniestro == id_siniestro))
    if siniestro is not None:
        return siniestro

    clean_id = id_siniestro.split("|")[0].strip()
    if clean_id != id_siniestro:
        siniestro = db.scalar(base.where(Siniestro.id_siniestro == clean_id))
        if siniestro is not None:
            return siniestro

    return db.scalar(base.where(Siniestro.id_siniestro.ilike(f"{clean_id}%")).limit(1))
