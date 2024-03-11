import io
import logging
import socketserver
from http import server
from threading import Condition
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
import cv2
from libcamera import controls
import numpy as np
import socket


def get_ipv4_address(hostname):
    try:
        ip_address = socket.gethostbyname(hostname)
        return ip_address
    except socket.error:
        return None


# Get the IP addresses for "rightcam.local" and "leftcam.local"
rightip = get_ipv4_address("rightcam.local")
leftip = get_ipv4_address("leftcam.local")

PAGE = f"""
<html>
    <head>
        <style>
            body, html {{
                margin: 0;
                padding: 0;
                height: 100%;
                overflow: hidden;
            }}
            .viewfinder-container {{
                display: flex;
                height: 100%;
            }}
            .viewfinder {{
                flex: 1;
                display: flex;
                flex-direction: row;
                justify-content: center;
                align-items: center;
                text-align: center;
                height: 100%;
            }}
            .viewfinder-item {{
                max-width: 100%;
                max-height: 100%;
               
                
            }}
            .ip-container {{
                font-size: 24px;
                font-weight: bold;
                position: absolute;
                bottom: 10px;
                left: 10px;
                background-color: rgba(255, 255, 255, 0.7);
                padding: 10px;
            }}
            .ip-text {{
                display: inline-block;
                margin-right: 10px;
            }}
            .fullscreen-button {{
                position: absolute;
                top: 10px;
                right: 10px;
                z-index: 1;
            }}
        </style>
    </head>
    <body>
        <button class="fullscreen-button" onclick="toggleFullscreen()">Toggle Fullscreen</button>
        <div class="viewfinder-container">
            <div class="viewfinder">
                <img class="viewfinder-item" src="http://{rightip}:8000/stream.mjpg" "/>

                <img class="viewfinder-item" src="http://{leftip}:8000/stream.mjpg" "/>

            </div>
            <div class="ip-container">
                <p class="ip-text"><a href="http://{rightip}:8000" class="ip-link">Click If video doesn't work</a></p>
                <p class="ip-text"><a href="http://{leftip}:8000" class="ip-link">Click If video doesn't work</a></p>
            </div>
        </div>
        <script>
            function toggleFullscreen() {{
                const container = document.querySelector(".viewfinder");
                if (!document.fullscreenElement) {{
                    container.requestFullscreen().catch(err => {{
                        console.error(`Error attempting to enable full-screen mode:`);
                    }});
                }} else {{
                    document.exitFullscreen().catch(err => {{
                        console.error(`Error attempting to exit full-screen mode: `);
                    }});
                }}
            }}
        </script>
    </body>
</html>
"""

def apply_barrel_distortion(frame):
    k1 = 0.2
    k2 = 0.05
    frame = np.frombuffer(frame, dtype=np.uint8)
    image = cv2.imdecode(frame, cv2.IMREAD_COLOR)

    # Assuming your image size is 1536x864, adjust it accordingly if needed
    image_width = 720
    image_height =720

    # Calculate optimal focal lengths (fx and fy)
    fx = image_width / 2
    fy = image_height / 2

    # Set the optical center at the center of the image
    cx = image_width / 2
    cy = image_height / 2

    # Create the camera matrix
    camera_matrix = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float32)

    # Distortion Co-eff
    dist_coeffs = np.array([k1, k2, 0, 0, 0], dtype=np.float32)

    # Apply the distortion correction
    undistorted_image = cv2.undistort(image, camera_matrix, dist_coeffs)

    _, encoded_frame = cv2.imencode(".jpg", undistorted_image)
    return encoded_frame.tobytes()


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header(
                'Content-Type', 'multipart/x-mixed-replace;boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame

                    # Apply barrel Distortion
                    #distorted_frame = apply_barrel_distortion(frame)
                    distorted_frame = frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(distorted_frame))
                    self.end_headers()
                    self.wfile.write(distorted_frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))

        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True




picam2 = Picamera2()

picam2.configure(picam2.create_video_configuration(main={"size": (512, 512)}))
output = StreamingOutput()
picam2.start_recording(JpegEncoder(num_threads=4), FileOutput(output))

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()
finally:
    picam2.stop_recording()
