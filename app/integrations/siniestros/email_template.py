from __future__ import annotations

from decimal import Decimal

from app.models.siniestro import Siniestro


def _money(value: Decimal | float | int | str) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return f"${amount:,.2f} USD"


def build_confirmation_email(siniestro: Siniestro) -> tuple[str, str]:
    insured_name = siniestro.beneficiario or siniestro.id_asegurado
    email = f"{insured_name.lower().replace(' ', '.')}@gmail.com"

    html_template = f"""
        <div style="background-color: #f4f6f9; padding: 30px; font-family: sans-serif; color: #081f3f;">
          <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
            <div style="background-color: #081f3f; padding: 25px; text-align: center; border-bottom: 4px solid #00adef;">
              <h2 style="color: #ffffff; margin: 0; font-size: 20px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase;">Aseguradora del Sur</h2>
              <p style="color: #00adef; margin: 5px 0 0 0; font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase;">Ficha Registral Siniestro • ShieldMind AI</p>
            </div>
            <div style="padding: 30px;">
              <p style="font-size: 14px; line-height: 1.5; font-weight: 600; color: #1e293b;">Estimado/a {insured_name},</p>
              <p style="font-size: 13px; line-height: 1.6; color: #475569;">Le confirmamos que su reporte de siniestro ha sido ingresado exitosamente en nuestra plataforma de triaje con inteligencia artificial. A continuación, detallamos la Ficha Registral Oficial emitida bajo radicado.</p>

              <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; text-align: center; border-radius: 6px; margin: 20px 0;">
                <span style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; display: block; margin-bottom: 4px;">Código de Radicado Oficial</span>
                <span style="font-family: monospace; font-size: 22px; font-weight: 900; color: #00adef; letter-spacing: 1px;">{siniestro.id_siniestro}</span>
              </div>

              <h3 style="font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; border-bottom: 2px solid #f1f5f9; padding-bottom: 6px; color: #081f3f; margin-top: 25px;">Detalles de la Ficha Registral</h3>

              <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px;">
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9; width: 45%;">Ramo de Seguro:</td>
                  <td style="padding: 8px 0; color: #1e293b; border-bottom: 1px solid #f1f5f9; font-weight: 600;">{siniestro.ramo}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9;">Código de Póliza:</td>
                  <td style="padding: 8px 0; color: #1e293b; border-bottom: 1px solid #f1f5f9; font-family: monospace;">{siniestro.id_poliza}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9;">Identificación del Asegurado:</td>
                  <td style="padding: 8px 0; color: #1e293b; border-bottom: 1px solid #f1f5f9;">{siniestro.id_asegurado}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9;">Fecha del Accidente:</td>
                  <td style="padding: 8px 0; color: #1e293b; border-bottom: 1px solid #f1f5f9;">{siniestro.fecha_ocurrencia}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9;">Fecha de Reporte:</td>
                  <td style="padding: 8px 0; color: #1e293b; border-bottom: 1px solid #f1f5f9;">{siniestro.fecha_reporte}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9;">Monto Reclamado:</td>
                  <td style="padding: 8px 0; color: #17478e; border-bottom: 1px solid #f1f5f9; font-weight: 800;">{_money(siniestro.monto_reclamado)}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9;">Sucursal:</td>
                  <td style="padding: 8px 0; color: #1e293b; border-bottom: 1px solid #f1f5f9;">{siniestro.sucursal}</td>
                </tr>
                <tr>
                  <td style="padding: 8px 0; font-weight: 700; color: #64748b; border-bottom: 1px solid #f1f5f9;">Estado Inicial:</td>
                  <td style="padding: 8px 0; color: #d97706; border-bottom: 1px solid #f1f5f9; font-weight: 700;">{siniestro.estado}</td>
                </tr>
              </table>

              <div style="margin-top: 25px; padding: 15px; background-color: #f8fafc; border-left: 4px solid #081f3f; border-radius: 4px;">
                <span style="font-size: 11px; font-weight: 700; color: #081f3f; text-transform: uppercase; display: block; margin-bottom: 5px;">Descripción de Hechos Reportados</span>
                <p style="margin: 0; font-size: 11.5px; line-height: 1.5; color: #334155; font-style: italic;">
                  "{siniestro.descripcion}"
                </p>
              </div>

              <p style="font-size: 11px; color: #64748b; line-height: 1.5; margin-top: 30px; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 15px;">
                Este es un mensaje de notificación automatizado enviado bajo las políticas de transparencia y explicabilidad ética de <strong>Aseguradora del Sur</strong>.<br/>
                Para consultas de su liquidación, por favor contacte a su bróker asignado.
              </p>
            </div>
            <div style="background-color: #f8fafc; padding: 15px; text-align: center; font-size: 10px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
              ShieldMind AI • © 2026 Aseguradora del Sur S.A. Todos los derechos reservados.
            </div>
          </div>
        </div>
      """

    message = f"Correo de confirmación simulado y despachado con éxito a {email}."
    return html_template.strip(), message
