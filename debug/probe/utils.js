import { getServerDateTime } from './DateTime.js?202511139';

/**
 * 判定するデバイスがモバイルかどうかを返す関数
 *
 * @returns {boolean} - モバイルデバイスならtrue、それ以外はfalse
 */
function isMobile() {
  const isMobile = window.matchMedia('(max-width: 767px)').matches;
  return isMobile;
}

export const breakP = {
  get _PC() {
    return !isMobile()
  },
  get _SP(){
    return isMobile()
  }
};



/**
 * サムネイルにつく動画の尺のデータ属性のフォーマット
 *
 * js-movieTimeLengthFormat に対して
 * テキストから aria-label を追加
 */
export function movieTimeLengthDataFormatter() {
  const movieTimeLengthFormats = document.querySelectorAll('.js-movieTimeLengthFormat');

  movieTimeLengthFormats.forEach(elm => {
    const timeLengthTxt = elm.textContent;
    const minutes = timeLengthTxt.split(':')[0];
    const seconds = timeLengthTxt.split(':')[1];
    const ariaTxt = `${minutes}分${seconds}秒`;
    elm.setAttribute('aria-label', ariaTxt);
  });
}

/**
 * 指定された日付に関連するjsonデータを取得する関数
 *
 * @param {string} path - フェッチするJSONファイルのパス
 * @param {string} date - データを取得する日付
 * @returns {Promise<Array>} - 取得したデータの配列
 */
export async function fetchDateNamedJson(path, date) {
  try {
    const response = await fetch(`${path}${date}.json`);
    return await response.json();
  } catch (error) {
    console.error(`${date} のデータを取得できませんでした: ${error}`);
    return [];
  }
}

/**
 * 指定された日付範囲に関連するすべての記事データを取得する関数
 *
 * @param {Array} dates - 記事データを取得する日付の配列
 * @param {string} path - フェッチするjsonファイルのパス
 * @returns {Promise<Object>} - 取得したすべての記事データ
 */
export async function fetchAllData(dates, path) {
  const allArticles = {};
  for (const date of dates) {
    allArticles[date.yyyy_mm_dd] = await fetchDateNamedJson(path, date.yyyy_mm_dd);
  }
  return allArticles;
}

/**
 * jsonデータ内の日付パラメータを基準にソートする関数
 *
 * @param {Array} data - jsonデータリスト
 * @param {string} dateParam - jsonデータ内のソートするYYYY-MM-DD HH:mmnのキー
 * @param {boolean} reverse - 逆順ソートにするかどうか
 * @returns {Array} sortedData - ソートした配列
 */
export function sortDataByDateTime(data, dateParam, reverse = false) {
  const sortedData = data.sort((a, b) => {
    const dataA = new Date(a[dateParam].replace(/-/g, '/'));
    const dataB = new Date(b[dateParam].replace(/-/g, '/'));
    return reverse ? dataB - dataA : dataA - dataB;
  });
  return sortedData;
}

/**
 * カードが含まれていないカード グループごとにメッセージを表示する関数
 *
 * @param {string} text - 表示されるメッセージ
 * @param  {...any} cardsGroup - 空かどうかをチェックするカード グループ
 */
export function displayMessageForEmptyCardGroups(text, ...cardsGroup) {
  cardsGroup.forEach(card => {
    $(card).each(function () {
      const group = $(this);
      if (!group.find('.generalCard').length) {
        group.html(
          `<li class="noDataBlk">
            <div class="noDataBlk__inner">
              <p class="noDataBlk__txt">${text}</p>
            </div>
          </li>`
        );
      }
    });
  });
}

/**
 * カードが含まれていないカード グループセクションに対して「もっとみる」リンクのトルツメ
 *
 * @param  {...any} cardsGroup - 空かどうかをチェックするカード グループ
 */
export function removeMoreLinkInSection(...cardGroup) {
  $(cardGroup).each(function () {
    const group = $(this);
    if (!group.find('.generalCard').length) {
      group.closest('.generalSect, .newsSubSect').find('.moreLink').remove();
    }
  });
}

/**
 * HTML要素の属性値に日時情報を持つ要素を取得し、現在の日時と比較して、未来の日時を持つ要素を削除する処理を行う
 */
export async function checkStatusDate() {
  if (0 < $('[data-status_date]').length) {
    //未来日のデータはタグごと削除する
    const time = await getServerDateTime().then(data => {
      const result = data.replace(/-/g, '/');
      return result;
    });
    const date = new Date(time);
    const year = date.getFullYear();
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const hours = date.getHours();
    const minutes = date.getMinutes();
    const ymdhi =
      year +
      '-' +
      ('00' + month).slice(-2) +
      '-' +
      ('00' + day).slice(-2) +
      ' ' +
      ('00' + hours).slice(-2) +
      ':' +
      ('00' + minutes).slice(-2);

    let vod_count = 0;
    let vod_category = 0;
    const max_vod_count = 4;
    $('[data-status_date]').each(function () {
      if ($(this).hasClass('common_video_data')) {
        //詳細ページ用のタグは削除しない
        return;
      }

      if (ymdhi < $(this).attr('data-status_date')) {
        $(this).remove();
        return;
      } else {
        $(this).show();
      }

      if ($(this).attr('data-vod_category')) {
        if ($(this).attr('data-vod_category') != vod_category) {
          vod_category = $(this).attr('data-vod_category');
          vod_count = 0;
        }
        if (vod_count >= max_vod_count) {
          $(this).remove();
          return;
        }
        vod_count++;
      }
    });

    $('[data-status_end_date]').each(function () {
      if ($(this).attr('data-status_end_date') && $(this).attr('data-status_end_date') < ymdhi) {
        $(this).remove();
        return;
      } else {
        $(this).show();
      }
    });

    if (0 < $('[data-vod_child_category]').length) {
      $('[data-vod_child_category]').each(function () {
        if ($(this).find('.generalCard').length <= 0) {
          $(this).remove();
        }
      });
    }
  }
}

/**
 * クリックしたら直前に開いていたページへ戻る
 */
export function backToPrevPage() {
  const buttons = document.querySelectorAll('.js-backToPrevPage');
  buttons.forEach(button => {
    button.addEventListener('click', () => {
      history.go(-1);
    });
  });
}

/**
 * カードグループの出力件数を4件に制御（JSON以外で出力されている部分）
 * @param  {...any} groupSelectors - カードグループ
 */
export function limitedViewCards(...groupSelectors) {
  const MAX_VIEW_LENGTH = 4;

  groupSelectors.forEach(groupSelector => {
    const groups = document.querySelectorAll(groupSelector);
    groups.forEach(group => {
      const cards = group.querySelectorAll('.generalCard');

      cards.forEach((card, index) => {
        if (index >= MAX_VIEW_LENGTH) {
          card.remove();
        }
      });
    });
  });
}
