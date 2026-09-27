<?php
/*
Plugin Name: Facebook Video Downloader
Plugin URI: https://yourwebsite.com
Description: A WordPress plugin to fetch and download Facebook videos using RapidAPI.
Version: 1.3
Author: Your Name
Author URI: https://yourwebsite.com
*/

if (!defined('ABSPATH')) {
    exit; // Exit if accessed directly
}

// Create the plugin menu in the WordPress admin panel
function fb_video_downloader_menu() {
    add_menu_page('FB Video Downloader', 'FB Downloader', 'manage_options', 'fb-video-downloader', 'fb_video_downloader_page');
}
add_action('admin_menu', 'fb_video_downloader_menu');

// Plugin page content in admin panel
function fb_video_downloader_page() {
    echo '<div class="wrap">';
    echo '<h2>Facebook Video Downloader</h2>';
    echo do_shortcode('[fb_video_downloader]');
    echo '</div>';
}

// Function to fetch the video link

// function fetch_fb_video_link($url) {
//     $api_url = 'https://facebook-video-downloader9.p.rapidapi.com/api/v1/videos/download?url=' . urlencode($url);

//     $response = wp_remote_get($api_url, [
//         'headers' => [
//             'x-rapidapi-host' => 'facebook-video-downloader9.p.rapidapi.com',
//             'x-rapidapi-key'  => '1d1ff19024msh59ecd661e73bcb5p135ae5jsna53974acd9e1',
//         ],
//         'timeout' => 15,
//     ]);

//     if (is_wp_error($response)) {
//         return null;
//     }

//     $body = wp_remote_retrieve_body($response);
//     $data = json_decode($body, true);

//     if (
//         isset($data['status']) && $data['status'] === 'success' &&
//         isset($data['data']['download']['sd']['url'])
//     ) {
//         return [
//             'title' => $data['data']['video']['title'] ?? 'Untitled',
//             'thumbnail' => $data['data']['video']['thumbnail_url'] ?? '',
//             'video_url' => $data['data']['download']['sd']['url'],
//         ];
//     }
//      return array(
//         'title' => 'Facebook Video', // Get actual title if possible
//         'thumbnail' => '', // URL to thumbnail image
//         'video_url' => '' //

//     return null;
// }

// function fetch_fb_video_link($video_url) {
//     $api_url = "https://getmyfb.com/process";
    
//     $post_fields = http_build_query([
//         'id' => $video_url,
//         'locale' => 'en'
//     ]);
    
//     $headers = [
//         "Content-Type: application/x-www-form-urlencoded"
//     ];
    
//     $ch = curl_init();
//     curl_setopt($ch, CURLOPT_URL, $api_url);
//     curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
//     curl_setopt($ch, CURLOPT_POST, true);
//     curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
//     curl_setopt($ch, CURLOPT_POSTFIELDS, $post_fields);
//     curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 20);
//     curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false); // optional for local testing

//     $response = curl_exec($ch);

//     if (curl_errno($ch)) {
//         echo "<p style='color:red;'>cURL Error: " . curl_error($ch) . "</p>";
//         return false;
//     }

//     curl_close($ch);

//     echo "<pre>"; print_r($response); echo "</pre>"; 

//     if (preg_match('/href="(https:\/\/[^"]+\.mp4[^"]*)"/', $response, $matches)) {
//         $video_url = $matches[1];
//         echo "<video width='320' height='240' controls><source src='$video_url' type='video/mp4'>Your browser does not support the video tag.</video>";
//         return ['video_url' => $video_url];
//     } else {
//         // echo "<p style='color:red;'>Error: Could not extract video URL. It might be private or protected.</p>";
//     }

//     return false;
// }




// function fb_video_downloader_shortcode() {
//     ob_start();
/*
//     ?>
//     <form method="post" action="">
//         <label for="fb_video_url"></label>
//         <input type="text" name="fb_video_url" id="fb_video_url" required>
//         <input type="submit" name="download_fb_video" value="Download Video">
//     </form>
*/

//     <?php
//     if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['download_fb_video'])) {
//         if (!empty($_POST['fb_video_url'])) {
//             $video_url = sanitize_text_field($_POST['fb_video_url']);
//             $video_details = fetch_fb_video_link($video_url);
//             $title = isset($video_details['title']) ? htmlspecialchars($video_details['title']) : 'No title available';


//             if ($video_details) {
//                 echo "<div style='margin-top: 20px;'>";
//                   if ($title) {
//                 echo "<h3>Video Title: $title</h3>";
//             } else {
//                 echo "<img src='" . esc_url($video_details['thumbnail']) . "' alt='Video Thumbnail' style='max-width: 300px; display: block; margin-bottom: 10px;'>";
//             }
//                 // Modified download link to force download
//                 echo "<p><strong>Download Link:</strong> <a href='" . esc_url($video_details['video_url']) . "' style='background: #007bff; color: white; border: none; padding: 8px 15px; cursor: pointer;' onclick=\"window.open('" . esc_url(admin_url('admin-ajax.php')) . "?action=fb_download_video&url='+encodeURIComponent('" . esc_url($video_details['video_url']) . "'), '_blank'); return false;\">Start download</a></p>";
                
//                 // // Alternative method using a direct download button
//                 // echo "<form method='post' action='" . esc_url(admin_url('admin-ajax.php')) . "'>";
//                 // echo "<input type='hidden' name='action' value='fb_download_video'>";
//                 // echo "<input type='hidden' name='video_url' value='" . esc_url($video_details['video_url']) . "'>";
//                 // echo "<input type='submit' value='Download Now' style='background: #007bff; color: white; border: none; padding: 8px 15px; cursor: pointer;'>";
//                 // echo "</form>";
                
//                 echo "</div>";
//             } else {
//                 echo "<p style='color:red;'>Failed to fetch video details. Please try again.</p>";
//             }
//         } else {
//             echo "<p style='color:red;'>Please enter a valid Facebook video URL.</p>";
//         }
//     }

//     return ob_get_clean();
// }
function fetch_fb_video_link($video_url) {
    $api_url = "http://51.21.251.244:8000/api/info?url=" . urlencode($video_url);
    $api_key = "fdownloader_sec_key_8492048123";

    $response = wp_remote_get($api_url, [
        'headers' => [
            'X-API-Key' => $api_key,
            'Accept'    => 'application/json',
        ],
        'timeout' => 60,
    ]);

    if (is_wp_error($response)) {
        echo "<p style='color:red;'>Error: Unable to connect to downloader service.</p>";
        return false;
    }

    $body = wp_remote_retrieve_body($response);
    $data = json_decode($body, true);

    if (!is_array($data)) {
        echo "<p style='color:red;'>Error: Invalid response from downloader service.</p>";
        return false;
    }

    $title = '';
    $thumbnail = '';

    if (isset($data['title'])) {
        $title = sanitize_text_field($data['title']);
    } elseif (isset($data['data']['title'])) {
        $title = sanitize_text_field($data['data']['title']);
    }

    if (isset($data['thumbnail'])) {
        $thumbnail = esc_url_raw($data['thumbnail']);
    } elseif (isset($data['data']['thumbnail'])) {
        $thumbnail = esc_url_raw($data['data']['thumbnail']);
    }

    if (!$title) {
        $title = 'Facebook Video';
    }

  $download_url = "http://51.21.251.244:8000/download?url=" . urlencode($video_url) . "&format=best&api_key=" . urlencode($api_key);

    return [
        'title' => $title,
        'thumbnail' => $thumbnail,
        'video_url' => $download_url,
    ];
}


function fb_video_downloader_shortcode() {
    ob_start();
    ?>
 <style>
 
 
  .fb-input {
    width: 100%;
    max-width: 500px;
    box-sizing: border-box;
  }

  @media (min-width: 768px) {
    .fb-input {
      width: 500px;
    }
  }

  #download_fb_video_btn {
    background: #16a34a !important;
    color: #fff !important;
  }

  /* Progress Bar */
  #download-progress {
    width: 100%;
    max-width: 560px;
    margin: 14px auto 0;
  }

  #download-progress > div {
    height: 12px !important;
    background: #f1f1f1 !important;
    border-radius: 50px !important;
    overflow: hidden;
    padding: 2px;
    box-sizing: border-box;
  }

  #progress-bar {
    height: 8px !important;
    min-width: 0;
    border-radius: 50px !important;
    background: linear-gradient(90deg, #16a34a, #4ade80, #16a34a) !important;
    background-size: 200% 100% !important;
    transition: width 0.5s ease-out;
    animation: greenProgressMove 1.5s linear infinite;
    box-shadow: 0 2px 8px rgba(22, 163, 74, 0.3);
    color: transparent !important;
    font-size: 0 !important;
    position: relative;
    overflow: hidden;
}

#progress-bar::after {
    content: "";
    position: absolute;
    top: 0;
    left: -45%;
    width: 40%;
    height: 100%;
    background: linear-gradient(
        90deg,
        transparent,
        rgba(255, 255, 255, 0.7),
        transparent
    );
    animation: progressShine 1.4s ease-in-out infinite;
}

@keyframes greenProgressMove {
    0% {
        background-position: 0% 50%;
    }
    100% {
        background-position: 200% 50%;
    }
}

@keyframes progressShine {
    0% {
        left: -45%;
    }
    100% {
        left: 110%;
    }
}

  #progress-bar::after {
    content: "";
    position: absolute;
    top: 0;
    left: -45%;
    width: 40%;
    height: 100%;
    background: linear-gradient(
      90deg,
      transparent,
      rgba(255,255,255,0.65),
      transparent
    );
    animation: progressShine 1.4s ease-in-out infinite;
  }

  #progress-text {
    margin: 7px 0 0 !important;
    text-align: center;
    font-size: 12px !important;
    font-weight: 600;
    color: #555 !important;
  }

  @keyframes progressMove {
    0% {
      background-position: 0% 50%;
    }
    100% {
      background-position: 200% 50%;
    }
  }

  @keyframes progressShine {
    0% {
      left: -45%;
    }
    100% {
      left: 110%;
    }
  }

  @media (max-width: 600px) {
    #download_fb_video_btn {
      width: 100% !important;
      box-sizing: border-box !important;
      margin-top: 10px !important;
    }
  }
  @keyframes greenProgressMove {
    0% {
        background-position: 0% 50%;
    }
    100% {
        background-position: 200% 50%;
    }
}
</style>
  <form method="post" action="" id="fb-video-downloader-form">

    <label for="fb_video_url"></label><br>
    <input type="text" name="fb_video_url" id="fb_video_url" class="fb-input" required placeholder="Enter Facebook Video URL">
    <input type="submit" name="download_fb_video" id="download_fb_video_btn" value="Download Video">
<p id="fetch-message" style="display:none; margin:10px 0; text-align:center; font-size:13px; font-weight:600; color:#555;">
    Fetching<span id="fetch-dots">...</span>
</p>
  <p id="fetch-message" style="display:none; margin:10px 0; text-align:center; font-size:13px; font-weight:600; color:#555;">
    Fetching...
</p>

    <div id="download-progress" style="display:none; margin-top:10px;">
        <div style="width:100%; background:#f0f0f0; border-radius:5px;">
            <div id="progress-bar" style="height:20px; width:0%; background:#4CAF50; border-radius:5px; text-align:center; color:white;"></div>
        </div>
        <p id="progress-text">Preparing download...</p>
    </div>

</form>
    
    <script>
    jQuery(document).ready(function($) {
        $('#fb-video-result').remove();
$('#fb_video_url').val('');
        $('#fb-video-downloader-form').on('submit', function(e) {
            e.preventDefault();
            
            var videoUrl = $('#fb_video_url').val();
            if (videoUrl) {
                var btn = $('#download_fb_video_btn');
                var progressDiv = $('#download-progress');
                var progressBar = $('#progress-bar');
                var progressText = $('#progress-text');
              var fetchMessage = $('#fetch-message');
var fetchDots = $('#fetch-dots');
var dots = 0;
var fetchingTimer;

btn.prop('disabled', true);
btn.val('Processing...');
progressDiv.show();
progressText.text('Processing video URL...');

fetchMessage.show();

fetchingTimer = setInterval(function() {
    dots = (dots + 1) % 4;
    fetchDots.text('.'.repeat(dots));
}, 400);

var fetchDots = 0;

fetchingTimer = setInterval(function() {
    fetchDots = (fetchDots + 1) % 4;
    fetchMessage.text('Fetching' + '.'.repeat(fetchDots));
}, 400);
                
                // First get the downloadable URL
                $.post(window.location.href, {
                    'fb_video_url': videoUrl,
                    'download_fb_video': true
                }, function(response) {
                var tempDiv = $('<div>').html(response);

var preview = tempDiv.find('div[style*="max-width:560px"]').first();
var downloadButton = tempDiv.find('#direct_download_btn').first();

var onclickCode = downloadButton.attr('onclick');
var match = onclickCode ? onclickCode.match(/downloadVideo\("([^"]+)"/) : null;
var downloadUrl = match ? match[1] : '';

$('#fb-video-result').remove();

clearInterval(fetchingTimer);
fetchMessage.hide();

if (preview.length) {
    preview.attr('id', 'fb-video-result');
    preview.find('#direct_download_btn').removeAttr('onclick');

    $('#fb-video-downloader-form').after(preview);

    preview.find('#direct_download_btn').on('click', function() {
        startDownload(downloadUrl);
    });
}
                    
                    if (downloadUrl) {
                       
                    } else {
                        progressText.html('Error: Could not get download URL. ' + tempDiv.find('p[style="color:red;"]').text());
                        btn.prop('disabled', false);
                        btn.val('Download Video');
                    }
                }).fail(function() {
                    progressText.text('Error: Failed to process video URL');
                    btn.prop('disabled', false);
                    btn.val('Download Video');
                });
            }
        });
        
        function startDownload(downloadUrl) {
    var btn = $('#download_fb_video_btn');
    var progressDiv = $('#download-progress');
    var progressBar = $('#progress-bar');
    var progressText = $('#progress-text');
    var fetchMessage = $('#fetch-message');

    progressDiv.show();

    progressBar.css({
        'width': '0%',
        'background': 'linear-gradient(90deg, #16a34a, #4ade80, #16a34a)',
        'background-size': '200% 100%',
        'animation': 'greenProgressMove 1.5s linear infinite'
    });

    progressText.text('Preparing your download...');

    var iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    iframe.src = '<?php echo admin_url('admin-ajax.php'); ?>?action=fb_download_video&video_url=' + encodeURIComponent(downloadUrl);
    document.body.appendChild(iframe);

    var progress = 0;

    var progressInterval = setInterval(function() {
        if (progress < 90) {
            progress += Math.random() * 7;

            if (progress > 90) {
                progress = 90;
            }

            progressBar.css('width', progress + '%');
            progressText.text('Preparing download... ' + Math.round(progress) + '%');
        }
    }, 500);

    iframe.onload = function() {
        clearInterval(progressInterval);

        progressBar.css('width', '100%');
        progressText.text('Download started ✓');

        setTimeout(function() {
            progressDiv.fadeOut(400, function() {
                progressBar.css('width', '0%');
                progressText.text('Preparing download...');
            });
        }, 1200);
    };
}}
    });
    </script>
    <?php

    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['download_fb_video'])) {
        if (!empty($_POST['fb_video_url'])) {
            $video_url = sanitize_text_field($_POST['fb_video_url']);
            $video_details = fetch_fb_video_link($video_url);

            if ($video_details && isset($video_details['video_url'])) {
                $title = $video_details['title'];
                $thumbnail = $video_details['thumbnail'];
                $video_link = esc_url($video_details['video_url']);

             echo "<div style='margin:14px auto 0; max-width:560px; background:#fff; border:1px solid #e8e8e8; border-radius:14px; padding:10px; box-shadow:0 4px 16px rgba(0,0,0,0.06);'>";

echo "<div style='display:flex; align-items:center; gap:12px;'>";

if ($thumbnail) {
    echo "<img src='" . esc_url($thumbnail) . "' alt='Video Thumbnail' style='width:105px; height:72px; object-fit:cover; border-radius:9px; flex-shrink:0;'>";
}

echo "<div style='min-width:0; flex:1;'>";
echo "<div style='font-size:13px; font-weight:600; color:#222; line-height:1.4; margin-bottom:7px; overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;'>" . esc_html($title) . "</div>";

echo "<button id='direct_download_btn' onclick='downloadVideo(\"" . esc_js($video_link) . "\")' style='background:#16a34a; color:#fff; border:0; border-radius:7px; padding:7px 13px; font-size:12px; font-weight:600; cursor:pointer; box-shadow:0 2px 6px rgba(22,163,74,0.22);'>↓ Download Video</button>";

echo "</div>";
echo "</div>";
echo "</div>";
                
                echo "<script>
                function downloadVideo(url) {
                    var btn = document.getElementById('direct_download_btn');
                    var progressDiv = document.getElementById('download-progress');
                    var progressBar = document.getElementById('progress-bar');
                    var progressText = document.getElementById('progress-text');
                    
                    btn.disabled = true;
                    btn.textContent = 'Downloading...';
                    progressDiv.style.display = 'block';
                    progressText.textContent = 'Starting download...';
                    
                    // Create hidden iframe for download
                    var iframe = document.createElement('iframe');
                    iframe.style.display = 'none';
                    iframe.src = '".admin_url('admin-ajax.php')."?action=fb_download_video&video_url=' + encodeURIComponent(url);
                    document.body.appendChild(iframe);
                    
                    // Fallback - re-enable button after 30 seconds
                    var timeout = setTimeout(function() {
                        btn.disabled = false;
                        btn.textContent = 'Download Video';
                        progressText.textContent = 'Download complete!';
                        setTimeout(function() {
                            progressDiv.style.display = 'none';
                        }, 3000);
                    }, 30000);
                    
                    // Simulate progress
                    var progress = 0;
                    var progressInterval = setInterval(function() {
                        progress += Math.random() * 10;
                        if (progress > 90) progress = 90;
                        progressBar.style.width = progress + '%';
                        progressBar.textContent = Math.round(progress) + '%';
                        progressText.textContent = 'Downloading... ' + Math.round(progress) + '%';
                    }, 500);
                    
                    iframe.onload = function() {
                        clearInterval(progressInterval);
                        clearTimeout(timeout);
                        progressBar.style.width = '100%';
                        progressBar.textContent = '100%';
                        progressText.textContent = 'Download complete!';
                        btn.disabled = false;
                        btn.textContent = 'Download Video';
                        setTimeout(function() {
                            progressDiv.style.display = 'none';
                        }, 3000);
                    };
                }
                </script>";
            } else {
                echo "<p style='color:red;'>Failed to retrieve video information or no downloadable link found.</p>";
            }
        } else {
            echo "<p style='color:red;'>Please enter a valid Facebook video URL.</p>";
        }
    }

    return ob_get_clean();
}
add_shortcode('fb_video_downloader', 'fb_video_downloader_shortcode');

function handle_fb_video_download() {
    if (!isset($_GET['video_url'])) {
        wp_die('Invalid request');
    }

    $video_url = esc_url_raw($_GET['video_url']);

    $filename = 'facebook_video_' . time() . '.mp4';

    header('Content-Type: video/mp4');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    header('Content-Transfer-Encoding: binary');
    header('Expires: 0');
    header('Cache-Control: must-revalidate');
    header('Pragma: public');

    while (ob_get_level()) {
        ob_end_clean();
    }

    $api_key = "fdownloader_sec_key_8492048123";

    $ch = curl_init();

    curl_setopt($ch, CURLOPT_URL, $video_url);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, false);
    curl_setopt($ch, CURLOPT_HEADER, false);
    curl_setopt($ch, CURLOPT_BUFFERSIZE, 8192);

    curl_setopt($ch, CURLOPT_HTTPHEADER, [
        "X-API-Key: $api_key",
        "Accept: */*"
    ]);

    curl_exec($ch);

    if (curl_errno($ch)) {
        curl_close($ch);
        wp_die('Download service error. Please try again.');
    }

    curl_close($ch);
    die();
}
add_action('wp_ajax_fb_download_video', 'handle_fb_video_download');
add_action('wp_ajax_nopriv_fb_download_video', 'handle_fb_video_download');

