# Staging local

Un ambiente igual al del VPS, pero en un equipo de desarrollo: corre el mismo
`infra/docker-compose.prod.yml` y el mismo `infra/desplegar.sh`, con un Nginx con HTTPS que hace el
papel del Nginx del servidor. Sirve para ensayar despliegues, reversiones y restauraciones antes de
hacerlos en el VPS, y para probar la app de campo en teléfonos de la misma red Wi-Fi.

Requisitos: Docker Desktop (Windows, con Git Bash) o Docker en Linux, y `openssl`.

## Levantarlo

```bash
infra/local/staging.sh todo          # o: infra/local/staging.sh todo 192.168.1.18
```

El comando:

1. crea `.env.local` con claves aleatorias y una CA local con un certificado para la IP de la red;
2. construye las imágenes `local/sapef-backend` y `local/sapef-estaticos` del commit actual (si hay
   cambios sin commit, la versión lleva el sufijo `-local<hora>`);
3. las despliega con `infra/desplegar.sh`, igual que en el VPS;
4. copia la base y los archivos de desarrollo (`sapef-dev`) al staging con `respaldar.sh` y
   `restaurar.sh`, así también se ensayan los respaldos con datos reales;
5. levanta el Nginx: web en `https://<ip>:8443`, app de campo en `https://<ip>:8444` y el
   certificado de la CA en `http://<ip>:8080`.

Todo queda en `.staging-local/` y `.env.local`, que no se suben al repositorio porque tienen datos
reales. El proyecto de Compose es `sapef-local` (puerto 8101) y no modifica la base de desarrollo.

## Día a día

| Necesito | Comando |
| --- | --- |
| Probar los cambios del código | `staging.sh construir` y `staging.sh desplegar` |
| Volver a la versión anterior | `staging.sh revertir` |
| Refrescar los datos desde desarrollo | `staging.sh datos` |
| Ver qué corre y en qué versión | `staging.sh estado` |
| Apagarlo / borrarlo | `staging.sh bajar` / `staging.sh borrar` |

Los usuarios y contraseñas son los mismos de la base de desarrollo, porque se copian con los datos.

## Teléfonos

1. El teléfono debe estar en la misma red Wi-Fi que el equipo.
2. Abrir `http://<ip>:8080`, descargar el certificado e instalarlo como **certificado de CA**:
   - **Android:** Ajustes › Seguridad › Cifrado y credenciales › Instalar un certificado ›
     Certificado de CA.
   - **iPhone:** abrir el enlace en Safari, instalar el perfil en Ajustes y activar la confianza
     total en Ajustes › General › Información › Ajustes de confianza de certificados.
3. Abrir `https://<ip>:8444` e instalar la app desde el menú del navegador.
4. **Al terminar, quitar el certificado del teléfono.** La llave de la CA está en
   `.staging-local/certs/ca.key`: mientras el teléfono confíe en ella, quien tenga esa llave podría
   suplantar sitios ante ese teléfono.

Si Windows pregunta por el firewall la primera vez, permitir Docker Desktop en redes privadas. Si
cambia la IP del equipo, `staging.sh preparar` y `staging.sh proxy` rehacen el certificado.
