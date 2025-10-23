# local-proxy-strava-heatmap
A local proxy to use the Strava heatmap in QGIS, using a XYZ layers

### Using in Qgis
After running the .py file, add a XYZ connection with URL http://[ip]:5000/heatmap/{z}/{x}/{y}.png with [ip] = 0.0.0.0 or 127.0.0.1 or localhost or your_ip_lan

### WARNING
This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
