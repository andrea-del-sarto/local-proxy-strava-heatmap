# local-proxy-strava-heatmap
A local proxy to use the Strava Heatmap as XYZ tiles in any GIS software

### Using in GIS software
After running the .py file, add a XYZ connection with URL http://[host]:5000/heatmap/{z}/{x}/{y}.png with [host] = 0.0.0.0 or 127.0.0.1 or localhost or <your_ip_lan>

#### Options
Choose activity from:
| ID | Activity | Description         | Default |
|---:|----------|---------------------|:-------:|
| 1  | all      | All activity        | **✓**  |
| 2  | run      | Running             | **X**  |
| 3  | ride     | Bicycle             | **X**  |
| 4  | winter   | Winter sport        | **X**  |
| 5  | water    | Water sport         | **X**  |


Choose color from:
| ID | Color   | Default |
|---:|---------|:-------:|
| 1  | hot     | **✓**   |
| 2  | blue    | **X**   |
| 3  | bluered | **X**   |
| 4  | purple  | **X**   |
| 5  | gray    | **X**   |

## WARNING
This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.

## LICENSE
This project is provided for educational and personal use only.
Respect the terms of service of Strava and Freemap.sk when using this proxy.
